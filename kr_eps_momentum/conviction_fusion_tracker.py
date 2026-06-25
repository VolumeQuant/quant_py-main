# -*- coding: utf-8 -*-
"""★융합(확신가중) 전용 forward 검증 추적기 — 독립 NTM 수집판 (2026-06-25 재구축).

설계 원칙:
  - kr eps 시스템(ntm_screening) 의존 제거. FnGuide 컨센서스를 production 유니버스에 *직접* 수집.
    (kr eps 테이블은 유니버스가 다르고 매일 쪼그라들어[210→90] top20 절반 미커버 → 별도 구축)
  - 외부 API 병렬 금지: get_consensus_batch(4스레드) 안 씀. get_consensus_data 순차 호출(delay).
  - TTM 실적EPS 분모: 지배주주당기순이익 우선, 없으면 당기순이익 폴백(브이엠처럼 지배지분 구분 없는 회사).

매일: production 보유(rank<=3)+컨텍스트(top20) → 기대성장(FnGuide 선행EPS / TTM실적EPS) → '확인' 표시 → 누적.
확인 = 그날 계산가능 종목 기대성장의 중앙값 이상 (cross-sectional, 자체 유니버스).
★ 이것만이 look-ahead 아닌 진짜 OOS. 60일+ 누적 후 확인 vs 미확인 격차로 융합 검증.
실행: python kr_eps_momentum/conviction_fusion_tracker.py  (재실행마다 누적, 당일 컨센은 캐시)
로그: conviction_fusion_log.csv / 컨센캐시: fusion_consensus_cache.csv"""
import sys, io, os, glob, json, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
import fnguide_crawler as fc
LOG = os.path.join(HERE, 'conviction_fusion_log.csv')
CACHE = os.path.join(HERE, 'fusion_consensus_cache.csv')
CONTEXT_N = 20   # production top-N 까지 컨센 수집(랭킹 기준셋) — 보유 top3는 항상 포함
FETCH_DELAY = 1.2  # FnGuide 순차 딜레이(초)

px = pd.read_parquet(sorted(glob.glob(ROOT + '/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0, np.nan)
pcol = {c: i for i, c in enumerate(px.columns)}; parr = px.values
pdi = {d.strftime('%Y%m%d'): i for i, d in enumerate(px.index)}; ptd = list(pdi.keys())
mc = pd.read_parquet(sorted(glob.glob(ROOT + '/data_cache/market_cap_ALL_*.parquet'))[-1])

_NM = None
def name(t6):
    global _NM
    if _NM is None:
        try: _NM = json.load(open(os.path.join(HERE, 'ticker_info_cache.json'), encoding='utf-8'))
        except Exception: _NM = {}
    for k in (t6, t6 + '.KS', t6 + '.KQ'):
        if k in _NM: return _NM[k].get('shortName', t6)
    return t6

def ttm_eps(t6):
    """TTM 실적EPS(원). 지배주주당기순이익 우선 → 없으면 당기순이익 폴백."""
    p = ROOT + f'/data_cache/fs_dart_{t6}.parquet'
    if not os.path.exists(p) or t6 not in mc.index: return None
    fs = pd.read_parquet(p); fs['rcept_dt'] = pd.to_datetime(fs['rcept_dt'], errors='coerce')
    sh = mc.loc[t6, '상장주식수']
    if not (sh > 0): return None
    for acct in ('지배주주당기순이익', '당기순이익'):
        q = fs[(fs['공시구분'] == 'q') & (fs['계정'] == acct) & (fs['rcept_dt'].notna())].sort_values('rcept_dt')
        v = q['값'].astype(float).values
        if len(v) >= 4:
            return (v[-4:].sum() * 1e8) / sh
    return None

def latest_production():
    """최신 production state: (기준일, 보유 top3, 컨텍스트 top-N)."""
    f = sorted(glob.glob(ROOT + '/state/ranking_*.json'))[-1]
    bd = os.path.basename(f)[8:16]
    rk = sorted(json.load(open(f, encoding='utf-8'))['rankings'], key=lambda z: z.get('rank', 99))
    return bd, [x['ticker'] for x in rk[:3]], [x['ticker'] for x in rk[:CONTEXT_N]]

def load_cache():
    if os.path.exists(CACHE):
        return pd.read_csv(CACHE, dtype={'ticker': str, 'date': str})
    return pd.DataFrame(columns=['date', 'ticker', 'forward_eps', 'analyst_count', 'has_consensus'])

def collect_consensus(tickers, day8):
    """production 유니버스에 FnGuide 컨센 순차 수집(당일 캐시 재사용). forward_eps dict 반환."""
    cache = load_cache()
    have = set(cache[cache['date'] == day8]['ticker'])
    new = []
    todo = [t for t in tickers if t not in have]
    if todo:
        print(f"  FnGuide 컨센 수집 {len(todo)}종목 (순차, ~{len(todo)*FETCH_DELAY:.0f}초)...")
        for t in todo:
            try:
                d = fc.get_consensus_data(t)
                new.append({'date': day8, 'ticker': t,
                            'forward_eps': d.get('forward_eps') if d else None,
                            'analyst_count': d.get('analyst_count') if d else None,
                            'has_consensus': int(bool(d and d.get('has_consensus')))})
            except Exception:
                new.append({'date': day8, 'ticker': t, 'forward_eps': None, 'analyst_count': None, 'has_consensus': 0})
            time.sleep(FETCH_DELAY)
        cache = pd.concat([cache, pd.DataFrame(new)], ignore_index=True)
        cache.to_csv(CACHE, index=False)
    cur = cache[cache['date'] == day8]
    return {r['ticker']: r['forward_eps'] for _, r in cur.iterrows()
            if pd.notna(r['forward_eps']) and r['forward_eps'] > 0}

def price_on(t6, d8):
    if t6 not in pcol or d8 not in pdi: return None
    v = parr[pdi[d8], pcol[t6]]; return float(v) if v > 0 else None

def main():
    pbd, held3, ctx = latest_production()
    fwd_eps = collect_consensus(ctx, pbd)
    # 기대성장 = 선행EPS / TTM실적EPS  (컨텍스트 전체로 중앙값 기준 산출)
    grow = {}
    for t in ctx:
        fe = fwd_eps.get(t); te = ttm_eps(t)
        if fe and te and te > 0: grow[t] = fe / te
    med = float(np.median(list(grow.values()))) if grow else None
    print(f"\n=== 융합 forward 추적기 (독립 NTM 수집) ===")
    print(f"production 기준일 {pbd} / 컨텍스트 top{CONTEXT_N} 중 기대성장 계산 {len(grow)}종목 / 중앙값 {('%.2fx'%med) if med else 'NA'}\n")
    print(f"{'보유 top3':16s}{'rank':>5s}{'확인':>5s}{'기대성장':>10s}  (확인=중앙값 {('%.2fx'%med) if med else ''} 이상)")
    newrows = []
    for i, t in enumerate(held3, 1):
        g = grow.get(t)
        isc = (g is not None and med is not None and g >= med)
        if g is not None: gs = f"{(g-1)*100:+.0f}% ({g:.2f}x)"
        elif fwd_eps.get(t) is None: gs = "NA(컨센없음)"
        else: gs = "NA(TTM없음)"
        print(f"{i}. {name(t)[:12]:12s}{'':2s}{i:>3d}{'✅' if isc else '  ':>5s}{gs:>10s}")
        newrows.append({'run_date': pbd, 'prod_date': pbd, 'ticker': t, 'name': name(t), 'rank': i,
                        'has_consensus': int(fwd_eps.get(t) is not None), 'grow': round(g, 4) if g else '',
                        'confirmed': int(isc), 'median_grow': round(med, 4) if med else '',
                        'entry_px': price_on(t, pbd)})
    log = pd.DataFrame()
    if os.path.exists(LOG):
        log = pd.read_csv(LOG, dtype={'ticker': str, 'run_date': str, 'prod_date': str})
    log = pd.concat([log, pd.DataFrame(newrows)], ignore_index=True).drop_duplicates(['run_date', 'ticker'], keep='last')
    log.to_csv(LOG, index=False)
    print(f"\n로그 누적 → {os.path.basename(LOG)} ({log['run_date'].nunique()}일치, 오늘 {len(newrows)}행)")

    # === 누적 OOS (확인 vs 미확인 forward) ===
    last8 = ptd[-1]; cf, un = [], []
    for _, r in log.iterrows():
        d0 = str(r['prod_date']); p0 = price_on(str(r['ticker']).zfill(6), d0); p1 = price_on(str(r['ticker']).zfill(6), last8)
        if p0 and p1 and d0 < last8:
            (cf if r['confirmed'] == 1 else un).append((p1 / p0 - 1) * 100)
    print(f"\n=== 누적 OOS (→{last8}) ===")
    if cf or un:
        print(f"  확인종목  fwd 평균 {np.mean(cf) if cf else 0:+.2f}% (n={len(cf)})")
        print(f"  미확인종목 fwd 평균 {np.mean(un) if un else 0:+.2f}% (n={len(un)})")
        if cf and un: print(f"  격차 {np.mean(cf) - np.mean(un):+.2f}%p")
    nd = log['run_date'].nunique()
    print(f"  ⚠️ {nd}일 누적 = {'예비(증거 아님)' if nd < 60 else '검증 시작'}. 60일+ 권장.")

if __name__ == '__main__':
    main()
