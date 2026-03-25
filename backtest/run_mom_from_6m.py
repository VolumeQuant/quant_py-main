"""모멘텀 기간 재계산 — 6M ranking에서 V/Q/G 재사용, M만 교체
Usage: python run_mom_from_6m.py <period>
  period: 6m-1m, 12m-1m, 12m

6M ranking JSON에서:
- 유니버스 (종목 목록) 그대로
- value_s, quality_s, growth_s (rev_z, oca_z) 그대로
- momentum_s만 새 기간으로 재계산 (섹터 내 rank z-score)
- composite score 재계산 후 저장
"""
import sys, io, os, glob, json, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, r'C:\dev')

import pandas as pd
import numpy as np
from scipy.stats import norm, linregress

PERIOD = sys.argv[1]  # 6m-1m, 12m-1m, 12m
CACHE = r'C:\dev\data_cache'
# 원본 bt_2020~2025 (V/Q/G/M 정상, FnGuide 기반)
SRC_DIRS = [rf'C:\dev\state\bt_{y}' for y in range(2020, 2026)]
OUT_DIR = rf'C:\dev\state\bt_mom_{PERIOD.replace("-","")}'
OHLCV_FILE = os.path.join(CACHE, 'all_ohlcv_20190102_20260320.parquet')
MIN_SECTOR = 10

# v70 가중치
V_W, Q_W, G_W, M_W = 0.20, 0.20, 0.30, 0.30
G_REV = 0.7
FLOOR = -1.5

os.makedirs(OUT_DIR, exist_ok=True)

t0 = time.time()
print(f'OHLCV 로딩...', flush=True)
prices = pd.read_parquet(OHLCV_FILE).replace(0, np.nan)
print(f'OHLCV: {prices.index[0]} ~ {prices.index[-1]}, {prices.shape}', flush=True)

# 원본 ranking 파일 목록 (bt_2020~2025)
src_files = []
for d in SRC_DIRS:
    src_files.extend(glob.glob(os.path.join(d, 'ranking_*.json')))
src_files = sorted(src_files)
print(f'원본 ranking: {len(src_files)}개', flush=True)

LOOKBACK = {'6m-1m': 126, '12m-1m': 252, '12m': 252}
VOL_FLOOR = 15.0

def _rank_to_z(series):
    valid = series.dropna()
    if len(valid) < 3:
        return pd.Series(0, index=series.index)
    ranks = valid.rank(method='average')
    n = len(valid)
    u = (ranks - 0.375) / (n + 0.25)
    z = pd.Series(norm.ppf(u), index=valid.index).clip(-3, 3)
    return z.reindex(series.index, fill_value=0)

def sector_rank_zscore_raw(values, sectors):
    """프로덕션 동일: raw Blom, 카테고리 합산 후 1번만 restandardize"""
    full_z = _rank_to_z(values)
    if sectors is None:
        return full_z
    result = pd.Series(0.0, index=values.index)
    valid_mask = values.notna()
    for sec in sectors[valid_mask].unique():
        sec_mask = (sectors == sec) & valid_mask
        if sec_mask.sum() >= MIN_SECTOR:
            result[sec_mask] = _rank_to_z(values[sec_mask])
        else:
            result[sec_mask] = full_z[sec_mask]
    return result

def k_ratio(s):
    if len(s) < 20:
        return np.nan
    log_cum = np.log(s / s.iloc[0])
    x = np.arange(len(log_cum))
    try:
        slope, _, _, _, stderr = linregress(x, log_cum.values)
        return slope / stderr if stderr > 0 else 0
    except:
        return 0

def compute_momentum(date_str, tickers, sectors_map):
    """새 기간의 모멘텀 계산 → 섹터 rank z-score → momentum_s"""
    dt = pd.Timestamp(date_str)
    if dt not in prices.index:
        return {}

    lookback = LOOKBACK[PERIOD]
    min_req = lookback + 1

    mom_dict = {}
    kr_dict = {}
    sec_list = {}

    for tk in tickers:
        if tk not in prices.columns:
            continue
        s = prices[tk].loc[:dt].dropna()
        if len(s) < min_req:
            continue
        cur = s.iloc[-1]
        if cur <= 0 or pd.isna(cur):
            continue

        try:
            if PERIOD == '6m-1m':
                p_start = s.iloc[-(126 + 1)]
                p_1m = s.iloc[-22]
                if p_start <= 0 or p_1m <= 0: continue
                ret = (p_1m / p_start - 1) * 100
                daily_rets = s.iloc[-(126 + 1):-21].pct_change().dropna()
            elif PERIOD == '12m-1m':
                p_start = s.iloc[-(252 + 1)]
                p_1m = s.iloc[-22]
                if p_start <= 0 or p_1m <= 0: continue
                ret = (p_1m / p_start - 1) * 100
                daily_rets = s.iloc[-(252 + 1):-21].pct_change().dropna()
            elif PERIOD == '12m':
                p_start = s.iloc[-(252 + 1)]
                if p_start <= 0: continue
                ret = (cur / p_start - 1) * 100
                daily_rets = s.iloc[-(252 + 1):].pct_change().dropna()
            else:
                continue

            annual_vol = daily_rets.std() * np.sqrt(252) * 100
            annual_vol = max(annual_vol, VOL_FLOOR)
            mom_dict[tk] = ret / annual_vol

            # K_ratio (항상 6M)
            kr_dict[tk] = k_ratio(s.iloc[-127:])
            sec_list[tk] = sectors_map.get(tk, '기타')
        except (IndexError, KeyError):
            continue

    if len(mom_dict) < 3:
        return {}

    # 섹터 내 rank z-score (raw, 프로덕션 동일)
    tks = list(mom_dict.keys())
    mom_z = sector_rank_zscore_raw(
        pd.Series({tk: mom_dict[tk] for tk in tks}),
        pd.Series({tk: sec_list[tk] for tk in tks}))
    kr_z = sector_rank_zscore_raw(
        pd.Series({tk: kr_dict[tk] for tk in tks}),
        pd.Series({tk: sec_list[tk] for tk in tks}))

    # 카테고리 합산 후 restandardize (프로덕션 동일)
    combined = (mom_z.fillna(0) + kr_z.fillna(0)) / 2
    if combined.std() > 0:
        combined = combined / combined.std()

    return combined.to_dict()

# 처리
count = 0
skip = 0
for fp in src_files:
    date_str = os.path.basename(fp).replace('ranking_', '').replace('.json', '')
    out_fp = os.path.join(OUT_DIR, os.path.basename(fp))

    # resume
    if os.path.exists(out_fp):
        skip += 1
        continue

    with open(fp, 'r', encoding='utf-8') as f:
        data = json.load(f)

    rankings = data.get('rankings', [])
    if not rankings:
        continue

    tickers = [r['ticker'] for r in rankings]
    sectors_map = {r['ticker']: r.get('sector', '기타') for r in rankings}

    # 새 모멘텀 계산
    new_mom = compute_momentum(date_str, tickers, sectors_map)

    # ranking 업데이트
    new_rankings = []
    for r in rankings:
        rc = dict(r)
        tk = rc['ticker']
        if tk in new_mom and not np.isnan(new_mom[tk]):
            rc['momentum_s'] = round(new_mom[tk], 4)

        # composite score 재계산 (v70 가중치)
        v = rc.get('value_s', 0) or 0
        q = rc.get('quality_s', 0) or 0
        m = rc.get('momentum_s', 0) or 0

        # growth: rev_z + oca_z with g_rev
        rev = rc.get('rev_z', 0) or 0
        oca = rc.get('oca_z', 0) or 0
        g = G_REV * rev + (1 - G_REV) * oca
        # g는 나중에 전체 restandardize 필요하므로 일단 raw 저장
        rc['_g_raw'] = g
        new_rankings.append(rc)

    # growth restandardize
    g_raws = [r['_g_raw'] for r in new_rankings]
    g_arr = np.array(g_raws)
    g_std = g_arr.std()
    if g_std > 0:
        g_std_arr = (g_arr - g_arr.mean()) / g_std
    else:
        g_std_arr = g_arr * 0

    for idx, r in enumerate(new_rankings):
        v = r.get('value_s', 0) or 0
        q = r.get('quality_s', 0) or 0
        m = r.get('momentum_s', 0) or 0
        g = g_std_arr[idx]
        r['growth_s_restd'] = round(g, 4)
        r['score'] = round(V_W * v + Q_W * q + G_W * g + M_W * m, 4)
        del r['_g_raw']

    # floor 필터 (4팩터 모두 체크 — 프로덕션 동일)
    filtered = []
    for r in new_rankings:
        factors = [r.get('value_s', 0), r.get('quality_s', 0),
                   r.get('growth_s_restd', 0), r.get('momentum_s', 0)]
        if any(f is not None and f < FLOOR for f in factors):
            continue
        del r['growth_s_restd']
        filtered.append(r)

    # 재정렬 + composite_rank
    filtered.sort(key=lambda x: -x['score'])
    for i, r in enumerate(filtered):
        r['composite_rank'] = i + 1
        r['rank'] = i + 1

    # 저장
    out_data = {'date': date_str, 'rankings': filtered}
    if 'metadata' in data:
        out_data['metadata'] = data['metadata']
    with open(out_fp, 'w', encoding='utf-8') as f:
        json.dump(out_data, f, ensure_ascii=False, indent=2)

    count += 1
    if count % 100 == 0:
        print(f'  {PERIOD}: {count}개 처리 ({time.time()-t0:.0f}초)', flush=True)

print(f'{PERIOD} 완료: {count}개 생성, {skip}개 스킵 ({time.time()-t0:.0f}초)')
