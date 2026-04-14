"""(d) 필터 적용: 모든 ranking 파일에서 분기 8개 미만 종목 제거 + composite_rank/wr 재계산

각 날짜 시점에서 ticker별 누적 분기 수를 확인하여 부족하면 제외.
"""
import sys, json, copy
import pandas as pd
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent.parent))

PROJECT = Path(__file__).parent.parent
STATE_DIR = PROJECT / 'state'
CACHE_DIR = PROJECT / 'data_cache'
PENALTY = 50
MIN_QUARTERS = 8

print('=== (d) 필터 적용: 분기 8개 미만 종목 제거 ===\n')

# 1. 모든 fs_dart에서 ticker별 분기 effective_date 리스트 구축
print('fs_dart 로딩 중...')
ticker_q_eff_dates = {}  # ticker → sorted list of (분기 8번째까지의 effective_date들)
fs_files = sorted(CACHE_DIR.glob('fs_dart_*.parquet'))
for fp in fs_files:
    tk = fp.stem.replace('fs_dart_', '')
    try:
        df = pd.read_parquet(fp)
        if '공시구분' not in df.columns:
            continue
        q_df = df[df['공시구분'] == 'q'].copy()
        if q_df.empty:
            continue
        # 기준일별 effective_date (rcept_dt 우선, 없으면 기준일 + 90일)
        q_df = q_df.drop_duplicates(subset=['기준일'])
        if 'rcept_dt' in q_df.columns:
            q_df['eff'] = q_df['rcept_dt'].fillna(q_df['기준일'] + pd.Timedelta(days=90))
        else:
            q_df['eff'] = q_df['기준일'] + pd.Timedelta(days=90)
        q_df = q_df.sort_values('기준일')
        ticker_q_eff_dates[tk] = q_df['eff'].tolist()
    except Exception:
        continue

print(f'fs_dart 종목 수: {len(ticker_q_eff_dates)}')

def is_insufficient(ticker, target_date):
    """target_date 시점에서 분기 8개 미만이면 True"""
    eff_list = ticker_q_eff_dates.get(ticker)
    if eff_list is None:
        return True  # fs_dart 없음 → 데이터 없음 → 제외
    target_ts = pd.Timestamp(target_date)
    available = sum(1 for eff in eff_list if eff <= target_ts)
    return available < MIN_QUARTERS


def process_dir(ranking_dir, label):
    print(f'\n[{label}] 처리 중...')
    files = sorted(f for f in ranking_dir.glob('ranking_*.json')
                   if len(f.stem.replace('ranking_', '')) == 8)
    print(f'  파일 수: {len(files)}')

    # 1단계: 각 파일에서 부족 종목 제거 + composite_rank 재계산
    all_data = {}
    dates = []
    removed_total = 0
    for fp in files:
        d = fp.stem.replace('ranking_', '')
        with open(fp, 'r', encoding='utf-8') as f:
            data = json.load(f)
        rankings = data.get('rankings', [])
        if not rankings:
            continue

        # 부족 종목 제거
        before = len(rankings)
        rankings = [r for r in rankings if not is_insufficient(r['ticker'], d)]
        removed = before - len(rankings)
        removed_total += removed

        # composite_rank 재부여 (score 기준 내림차순)
        rankings.sort(key=lambda x: x.get('score', 0), reverse=True)
        for i, r in enumerate(rankings):
            r['composite_rank'] = i + 1

        data['rankings'] = rankings
        all_data[d] = data
        dates.append(d)

    print(f'  제거된 종목 합계: {removed_total}건')

    # 2단계: weighted_rank 시간순 재계산
    dates.sort()
    cr_maps = {d: {r['ticker']: r['composite_rank'] for r in all_data[d].get('rankings', [])} for d in dates}
    for i, d in enumerate(dates):
        rankings = all_data[d].get('rankings', [])
        cr0 = cr_maps[d]
        cr1 = cr_maps[dates[i-1]] if i >= 1 else {}
        cr2 = cr_maps[dates[i-2]] if i >= 2 else {}
        for r in rankings:
            c0 = cr0.get(r['ticker'], PENALTY)
            c1 = cr1.get(r['ticker'], PENALTY)
            c2 = cr2.get(r['ticker'], PENALTY)
            r['weighted_rank'] = round(c0 * 0.5 + c1 * 0.3 + c2 * 0.2, 1)
        rankings.sort(key=lambda x: x['weighted_rank'])
        for j, r in enumerate(rankings):
            r['rank'] = j + 1
        all_data[d]['rankings'] = rankings

    # 3단계: 디스크 저장
    for d in dates:
        fp = ranking_dir / f'ranking_{d}.json'
        with open(fp, 'w', encoding='utf-8') as f:
            json.dump(all_data[d], f, ensure_ascii=False, indent=2)

    print(f'  저장 완료: {len(dates)}개 파일')
    # 4/14 검증 (있을 때만)
    if '20260414' in all_data:
        top10 = all_data['20260414']['rankings'][:10]
        print(f'\n  4/14 Top 10 (rank 기준):')
        for r in top10:
            print(f'    rank={r["rank"]:>2} cr={r["composite_rank"]:>3} wr={r["weighted_rank"]:>5.1f} {r["ticker"]} {r["name"]}')


process_dir(STATE_DIR, 'boost')
process_dir(STATE_DIR / 'defense', 'defense')

print('\n=== 완료 ===')
