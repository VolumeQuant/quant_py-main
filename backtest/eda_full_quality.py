"""전면 EDA: V/Q/M/U 데이터 품질 검토 (단일 스크립트, 멀티스레드)

목적: GS피앤엘 같은 데이터 품질 문제 종목을 V/Q/M/U 4영역에서 일제 검토
출력: 발견된 문제 + 필터 제안 (json + 콘솔)
"""
import sys, json, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import numpy as np

sys.stdout.reconfigure(encoding='utf-8')

PROJECT = Path(__file__).parent.parent
STATE_DIR = PROJECT / 'state'
CACHE_DIR = PROJECT / 'data_cache'

# ─── 데이터 1회 로딩 ───
print('=== 데이터 로딩 ===')
t0 = time.time()


def load_rankings(d):
    data = {}
    for fp in sorted(d.glob('ranking_*.json')):
        if len(fp.stem.replace('ranking_', '')) != 8:
            continue
        with open(fp, 'r', encoding='utf-8') as f:
            data[fp.stem.replace('ranking_', '')] = json.load(f)
    return data


print('  ranking 파일 로딩...')
boost_rankings = load_rankings(STATE_DIR)
defense_rankings = load_rankings(STATE_DIR / 'defense')
print(f'    boost {len(boost_rankings)}, defense {len(defense_rankings)}')

print('  fs_dart 로딩...')
fs_files = sorted(CACHE_DIR.glob('fs_dart_*.parquet'))
fs_dict = {}
for fp in fs_files:
    tk = fp.stem.replace('fs_dart_', '')
    try:
        fs_dict[tk] = pd.read_parquet(fp)
    except Exception:
        pass
print(f'    fs_dart {len(fs_dict)}개 종목')

print('  fundamental_pykrx 로딩...')
fund_files = sorted(CACHE_DIR.glob('fundamental_batch_ALL_*.parquet'))
fund_latest = pd.read_parquet(fund_files[-1])
print(f'    fundamental_batch (최신) {fund_latest.shape}')

print('  KRX sectors 로딩...')
sec_files = sorted(CACHE_DIR.glob('krx_sector_*.parquet'))
sec_latest = pd.read_parquet(sec_files[-1]) if sec_files else pd.DataFrame()
sector_map = {}
if not sec_latest.empty:
    col_code, col_sec = sec_latest.columns[0], sec_latest.columns[1]
    sector_map = {row[col_code]: str(row[col_sec]) for _, row in sec_latest.iterrows()}
print(f'    sector_map {len(sector_map)}개')

print(f'데이터 로딩 완료: {time.time()-t0:.1f}초\n')

# 모든 ranking 종목 풀 (boost ∪ defense)
all_tickers_in_rankings = set()
for d, rd in boost_rankings.items():
    for r in rd.get('rankings', []):
        all_tickers_in_rankings.add(r['ticker'])
for d, rd in defense_rankings.items():
    for r in rd.get('rankings', []):
        all_tickers_in_rankings.add(r['ticker'])
print(f'전체 ranking 등장 종목: {len(all_tickers_in_rankings)}개\n')

# ===========================================================
# 분석 함수들 (4영역)
# ===========================================================


def analyze_value():
    """V 팩터: PER/PBR/PCR/PSR 극단값 + 음수"""
    findings = {'name': 'Value', 'issues': [], 'suspect_tickers': set()}

    # 1. ranking 파일에서 PER, PBR 극단값 종목 (cr<=50, recent 30일)
    recent_dates = sorted(boost_rankings.keys())[-30:]
    extreme_per = {}  # ticker → list of (date, per)
    extreme_pbr = {}
    capped_value = {}  # value_s가 max/min에 가까운 종목

    for d in recent_dates:
        rl = boost_rankings[d].get('rankings', [])
        for r in rl[:50]:  # cr<=50
            tk = r['ticker']
            per = r.get('per')
            pbr = r.get('pbr')
            value_s = r.get('value_s')
            if per is not None and per > 100:
                extreme_per.setdefault(tk, []).append((d, per, r['name']))
            if pbr is not None and (pbr > 20 or pbr < 0):
                extreme_pbr.setdefault(tk, []).append((d, pbr, r['name']))
            if value_s is not None and abs(value_s) > 2.5:
                capped_value.setdefault(tk, []).append((d, value_s, r['name']))

    if extreme_per:
        findings['issues'].append({
            'type': 'PER > 100 (극단)',
            'count': len(extreme_per),
            'examples': [(tk, v[0][2], v[0][1]) for tk, v in list(extreme_per.items())[:5]]
        })
    if extreme_pbr:
        findings['issues'].append({
            'type': 'PBR > 20 또는 음수',
            'count': len(extreme_pbr),
            'examples': [(tk, v[0][2], v[0][1]) for tk, v in list(extreme_pbr.items())[:5]]
        })
    if capped_value:
        findings['issues'].append({
            'type': 'value_s |z| > 2.5',
            'count': len(capped_value),
            'examples': [(tk, v[0][2], v[0][1]) for tk, v in list(capped_value.items())[:5]]
        })
        findings['suspect_tickers'].update(capped_value.keys())

    # 2. fundamental_pykrx에서 PER=0 (적자, 이미 처리됨) 외 의심
    # PBR < 0 (자본잠식) 직접 체크
    if 'PBR' in fund_latest.columns:
        neg_pbr = fund_latest[fund_latest['PBR'] < 0]
        if len(neg_pbr) > 0:
            findings['issues'].append({
                'type': '자본잠식 (PBR < 0, fundamental)',
                'count': len(neg_pbr),
                'examples': neg_pbr.index[:5].tolist(),
            })
            findings['suspect_tickers'].update(neg_pbr.index.tolist())

    return findings


def analyze_quality():
    """Q 팩터: ROE 발산, 자본 음수, GPA/CFO 발산"""
    findings = {'name': 'Quality', 'issues': [], 'suspect_tickers': set()}

    # 1. ranking에서 ROE 극단값
    recent_dates = sorted(boost_rankings.keys())[-30:]
    extreme_roe = {}
    capped_quality = {}

    for d in recent_dates:
        rl = boost_rankings[d].get('rankings', [])
        for r in rl[:50]:
            tk = r['ticker']
            roe = r.get('roe')
            quality_s = r.get('quality_s')
            if roe is not None and (roe > 50 or roe < -30):
                extreme_roe.setdefault(tk, []).append((d, roe, r['name']))
            if quality_s is not None and abs(quality_s) > 2.5:
                capped_quality.setdefault(tk, []).append((d, quality_s, r['name']))

    if extreme_roe:
        findings['issues'].append({
            'type': 'ROE > 50% 또는 < -30% (극단)',
            'count': len(extreme_roe),
            'examples': [(tk, v[0][2], v[0][1]) for tk, v in list(extreme_roe.items())[:5]]
        })
        findings['suspect_tickers'].update(extreme_roe.keys())
    if capped_quality:
        findings['issues'].append({
            'type': 'quality_s |z| > 2.5',
            'count': len(capped_quality),
            'examples': [(tk, v[0][2], v[0][1]) for tk, v in list(capped_quality.items())[:5]]
        })
        findings['suspect_tickers'].update(capped_quality.keys())

    # 2. fs_dart에서 자본 음수 종목 직접 확인
    cap_negative = []
    for tk, fs_df in fs_dict.items():
        if '계정' not in fs_df.columns:
            continue
        cap_rows = fs_df[(fs_df['계정'] == '자본') & (fs_df['공시구분'] == 'q')]
        if cap_rows.empty:
            continue
        latest_cap = cap_rows.sort_values('기준일', ascending=False).iloc[0]['값']
        if pd.notna(latest_cap) and latest_cap <= 0:
            cap_negative.append(tk)
    if cap_negative:
        findings['issues'].append({
            'type': '자본 ≤ 0 (자본잠식, fs_dart)',
            'count': len(cap_negative),
            'examples': [tk for tk in cap_negative[:10]],
        })
        findings['suspect_tickers'].update(cap_negative)

    return findings


def analyze_momentum():
    """M 팩터: 모멘텀 극단값, 단기 데이터 종목"""
    findings = {'name': 'Momentum', 'issues': [], 'suspect_tickers': set()}

    # 1. 모멘텀 z-score 극단값
    recent_dates = sorted(boost_rankings.keys())[-30:]
    capped_mom = {}  # 어떤 모멘텀이라도 |z| > 2.5
    mom_diverge = {}  # 12m vs 6m 큰 차이

    for d in recent_dates:
        rl = boost_rankings[d].get('rankings', [])
        for r in rl[:50]:
            tk = r['ticker']
            mom_keys = ['mom_6m_s', 'mom_6m1m_s', 'mom_12m_s', 'mom_12m1m_s']
            for mk in mom_keys:
                v = r.get(mk)
                if v is not None and abs(v) > 2.7:
                    capped_mom.setdefault(tk, []).append((d, mk, v, r['name']))
            m6 = r.get('mom_6m_s', 0) or 0
            m12 = r.get('mom_12m_s', 0) or 0
            if abs(m12 - m6) > 3:  # 6m와 12m이 매우 다름
                mom_diverge.setdefault(tk, []).append((d, m6, m12, r['name']))

    if capped_mom:
        findings['issues'].append({
            'type': '모멘텀 |z| > 2.7 (극단)',
            'count': len(capped_mom),
            'examples': [(tk, v[0][3], v[0][1], v[0][2]) for tk, v in list(capped_mom.items())[:5]]
        })
        # 극단값 자체는 정상일 수 있으므로 suspect에 안 넣음

    if mom_diverge:
        findings['issues'].append({
            'type': '6m vs 12m 모멘텀 발산 |Δz| > 3',
            'count': len(mom_diverge),
            'examples': [(tk, v[0][3], f'6m={v[0][1]:.2f}', f'12m={v[0][2]:.2f}') for tk, v in list(mom_diverge.items())[:5]]
        })
        # 발산은 단기 급등/급락 신호일 수도 → 정보용

    return findings


def analyze_universe():
    """U: 유니버스 필터 우회 종목"""
    findings = {'name': 'Universe', 'issues': [], 'suspect_tickers': set()}

    # 1. 우선주 (티커 끝자리 ≠ 0)
    pref_in_ranking = []
    for tk in all_tickers_in_rankings:
        if len(tk) == 6 and tk[-1] != '0':
            pref_in_ranking.append(tk)
    if pref_in_ranking:
        findings['issues'].append({
            'type': '우선주 의심 (티커 끝자리 ≠ 0)',
            'count': len(pref_in_ranking),
            'examples': pref_in_ranking[:5],
        })
        findings['suspect_tickers'].update(pref_in_ranking)

    # 2. KRX 섹터 = '금융' 인데 EXCLUDE_KEYWORDS 매칭 안 된 종목
    EXCLUDE_KEYWORDS = ['금융', '은행', '증권', '보험', '캐피탈', '카드', '저축',
                        '지주', '홀딩스', 'SPAC', '스팩', '리츠', 'REIT',
                        '생명', '화재', '손해보험', 'IB투자', '벤처투자', '자산운용', '신탁']
    finance_bypass = []
    for d in sorted(boost_rankings.keys())[-5:]:
        rl = boost_rankings[d].get('rankings', [])
        for r in rl[:30]:
            sec = r.get('sector', '')
            nm = r.get('name', '')
            if sec == '금융' and not any(kw in nm for kw in EXCLUDE_KEYWORDS):
                finance_bypass.append((r['ticker'], nm, sec))
    finance_bypass = list({(tk, nm, sec) for tk, nm, sec in finance_bypass})
    if finance_bypass:
        findings['issues'].append({
            'type': '섹터=금융 + 키워드 매칭 안됨',
            'count': len(finance_bypass),
            'examples': finance_bypass[:5],
        })

    # 3. 종목명에 ETF/ETN/리츠/SPAC 키워드 정밀 검사
    etf_keywords = ['ETF', 'ETN', '인버스', '레버리지', '코스피200', '코스닥150']
    etf_in_ranking = []
    sample_dates = sorted(boost_rankings.keys())[-3:]
    for d in sample_dates:
        for r in boost_rankings[d].get('rankings', []):
            nm = r.get('name', '')
            if any(kw in nm for kw in etf_keywords):
                etf_in_ranking.append((r['ticker'], nm))
    etf_in_ranking = list(set(etf_in_ranking))
    if etf_in_ranking:
        findings['issues'].append({
            'type': 'ETF/인버스/레버리지 의심',
            'count': len(etf_in_ranking),
            'examples': etf_in_ranking[:5],
        })
        findings['suspect_tickers'].update(tk for tk, _ in etf_in_ranking)

    # 4. SPAC 의심 (기업인수목적, 글로벌 등)
    spac_keywords = ['기업인수목적', '글로벌', '리츠', 'REITs']
    spac_in_ranking = []
    for d in sample_dates:
        for r in boost_rankings[d].get('rankings', []):
            nm = r.get('name', '')
            for kw in spac_keywords:
                if kw in nm and not any(ek in nm for ek in EXCLUDE_KEYWORDS):
                    spac_in_ranking.append((r['ticker'], nm, kw))
                    break
    spac_in_ranking = list({(tk, nm, kw) for tk, nm, kw in spac_in_ranking})
    if spac_in_ranking:
        findings['issues'].append({
            'type': 'SPAC/리츠 의심 (키워드 매칭 안됨)',
            'count': len(spac_in_ranking),
            'examples': spac_in_ranking[:5],
        })
        findings['suspect_tickers'].update(tk for tk, _, _ in spac_in_ranking)

    # 5. fs_dart 분기 8개 미만 (이미 (d) 필터 적용됐어야)
    insufficient = []
    for tk in all_tickers_in_rankings:
        fs_df = fs_dict.get(tk)
        if fs_df is None or '공시구분' not in fs_df.columns:
            insufficient.append((tk, 0))
            continue
        q_dates = fs_df[fs_df['공시구분'] == 'q']['기준일'].unique()
        if len(q_dates) < 8:
            insufficient.append((tk, len(q_dates)))
    if insufficient:
        findings['issues'].append({
            'type': '(d) 필터 누락? fs_dart 분기 8개 미만',
            'count': len(insufficient),
            'examples': insufficient[:5],
        })

    return findings


# ===========================================================
# 멀티스레드 실행
# ===========================================================
print('=== Phase 1: 4영역 병렬 EDA ===\n')
t1 = time.time()

with ThreadPoolExecutor(max_workers=4) as ex:
    futures = {
        ex.submit(analyze_value): 'V',
        ex.submit(analyze_quality): 'Q',
        ex.submit(analyze_momentum): 'M',
        ex.submit(analyze_universe): 'U',
    }
    results = {}
    for fut in futures:
        label = futures[fut]
        results[label] = fut.result()

print(f'EDA 완료: {time.time()-t1:.1f}초\n')

# ===========================================================
# 보고서 출력
# ===========================================================
print('=' * 70)
print('전면 EDA 결과 보고서')
print('=' * 70)

all_suspects = set()
for label, fdg in results.items():
    print(f'\n[{label}: {fdg["name"]}]')
    if not fdg['issues']:
        print('  문제 없음 ✓')
        continue
    for issue in fdg['issues']:
        print(f'  ⚠ {issue["type"]} — {issue["count"]}건')
        for ex in issue['examples'][:3]:
            print(f'      {ex}')
    all_suspects.update(fdg['suspect_tickers'])

print(f'\n=== 종합 의심 종목: {len(all_suspects)}개 ===')

# JSON 저장
out = {
    'V': {**results['V'], 'suspect_tickers': list(results['V']['suspect_tickers'])},
    'Q': {**results['Q'], 'suspect_tickers': list(results['Q']['suspect_tickers'])},
    'M': {**results['M'], 'suspect_tickers': list(results['M']['suspect_tickers'])},
    'U': {**results['U'], 'suspect_tickers': list(results['U']['suspect_tickers'])},
    'all_suspects': list(all_suspects),
}
out_path = PROJECT / 'eda_full_quality_report.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, indent=2, default=str)
print(f'\n결과 저장: {out_path}')
