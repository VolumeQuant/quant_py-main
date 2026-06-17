# -*- coding: utf-8 -*-
"""raw + KRX 수정주가 → 신호용 가격 변형 4종 생성 (CA 타입 분해 연구).
KRX 수정주가에서 도출한 권위있는 per-event 보정계수를 방향별로 선택 적용:
  V_none  = raw (원주가, corp-OFF=4.31)         → 기존 _sp0b_co 재활용 (생성 안 함)
  V_all   = 전부 수정 (정직)                      → all_ohlcv_adj_*.parquet
  V_down  = 하락CA(무상증자/분할/유상권리락)만 보정, 병합(상승)은 raw → all_ohlcv_vdown_*.parquet
  V_up    = 상승CA(병합)만 보정, 하락은 raw        → all_ohlcv_vup_*.parquet
방향 판별: 수정주가 비율 ratio=adj/raw 의 시점별 점프. 하락CA는 과거가격을 ×(<1)로,
병합은 ×(>1)로 스케일 → factor<1=하락(무상/분할), factor>1=상승(병합).
RETURN(매매손익)은 항상 V_all 사용 — 신호만 변형."""
import sys, io, os, glob
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd

raw_f = sorted(glob.glob('C:/dev/data_cache/all_ohlcv_2017*_2026061*.parquet'))[-1]
adj_f = sorted(glob.glob('C:/dev/data_cache/adjusted_close_*.parquet'))[-1]
raw = pd.read_parquet(raw_f).replace(0, np.nan)
adjclose = pd.read_parquet(adj_f)
suffix = os.path.basename(raw_f).split('all_ohlcv_')[1]  # 20170601_20260617.parquet
print(f"raw {raw.shape} | adj fetch {adjclose.shape}")

THR = 0.02  # ratio 점프 2%+ = CA 이벤트
def selective(raw_s, adj_s, keep):
    """keep in {'all','down','up'}. 권위 수정주가 factor를 방향 선택 적용."""
    df = pd.DataFrame({'raw': raw_s, 'adj': adj_s})
    common = df.dropna()
    if len(common) < 2:
        return raw_s.copy()
    if keep == 'all':
        return adj_s.where(adj_s.notna(), raw_s)  # 전부 수정 = 수정주가 직접
    ratio = common['adj'] / common['raw']
    dlog = np.log(ratio).diff()
    factor = pd.Series(1.0, index=raw_s.index)
    nev = 0
    for d in common.index[1:]:
        dl = dlog.loc[d]
        if not np.isfinite(dl) or abs(dl) < THR:
            continue
        is_down = dl > 0  # ratio 상승(과거가격↓ 스케일) = 하락CA(무상증자/분할)
        if (keep == 'down' and is_down) or (keep == 'up' and not is_down):
            factor.loc[factor.index < d] *= np.exp(-dl)  # 권위 per-event factor
            nev += 1
    return raw_s * factor

variants = {'adj': 'all', 'vdown': 'down', 'vup': 'up'}
ca_stats = {'down': 0, 'up': 0}
# CA 이벤트 방향 통계 (전 종목)
for tk in adjclose.columns:
    if tk not in raw.columns:
        continue
    df = pd.DataFrame({'raw': raw[tk], 'adj': adjclose[tk]}).dropna()
    if len(df) < 2:
        continue
    dlog = np.log(df['adj'] / df['raw']).diff()
    for dl in dlog:
        if np.isfinite(dl) and abs(dl) >= THR:
            ca_stats['down' if dl > 0 else 'up'] += 1
print(f"CA 이벤트(전 종목): 하락(무상증자/분할/유상) {ca_stats['down']}건, 상승(병합) {ca_stats['up']}건")

for name, keep in variants.items():
    out = raw.copy()
    npatch = 0
    for tk in adjclose.columns:
        if tk not in out.columns:
            continue
        s = selective(raw[tk], adjclose[tk].reindex(raw.index), keep)
        if not s.equals(raw[tk]):
            npatch += 1
        out[tk] = s
    path = f'C:/dev/data_cache/all_ohlcv_{name}_{suffix}'
    out.to_parquet(path)
    print(f"[{name}] {keep}: {npatch}종목 변경 → {os.path.basename(path)}")

# 검증: 디바이스(무상증자=하락CA) — V_all/V_down은 보정, V_up은 raw 유지여야
print("\n검증 디바이스(187870) 4/27→4/28 종가:")
for name in ['adj', 'vdown', 'vup']:
    p = sorted(glob.glob(f'C:/dev/data_cache/all_ohlcv_{name}_*.parquet'))[-1]
    d = pd.read_parquet(p)
    if '187870' in d.columns:
        a = d.loc['2026-04-27', '187870']; b = d.loc['2026-04-28', '187870']
        print(f"  {name}: 4/27 {a:,.0f} → 4/28 {b:,.0f}" + ("  (보정됨)" if a < 30000 else "  (raw 유지=왜곡)"))
