# -*- coding: utf-8 -*-
"""사이징 오버레이 3종 검증 (선택 불변, 비중만 — '비중만 유효' 계열).
A) 섹터 쏠림 스케일: 보유 3종목 전부 동일섹터 → 노출 축소
B) 쇼크 브레이크: 전일 포트 수익 < -X% → N일 노출 축소
C) 포트 변동성 타게팅: 20일 실현변동성 기반 노출 스케일
전부 look-ahead 없음(당일 판단은 전일까지 정보). 하니스 = _fastexit_faithful 복제 E3X5S3+브레드스."""
import sys, io, os, glob, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd

R = 'C:/dev/claude-code/quant_py-main'
px = pd.read_parquet(R + '/data_cache/all_ohlcv_adj_20170601_20260629.parquet').replace(0, np.nan)
pcol = {c: i for i, c in enumerate(px.columns)}
parr = px.values
tdays = [d.strftime('%Y%m%d') for d in px.index]
tdi = {d: i for i, d in enumerate(tdays)}
kc = pd.read_parquet(R + '/data_cache/kospi_yf.parquet').iloc[:, 0]
ma20 = kc.rolling(20).mean(); ma80 = kc.rolling(80).mean()

CR = {}; dts = []
for f in sorted(glob.glob(R + '/state/ranking_*.json')):
    dt = os.path.basename(f)[8:16]
    if not (dt.isdigit() and len(dt) == 8 and dt >= '20190102' and dt in tdi):
        continue
    r = json.load(open(f, encoding='utf-8'))['rankings']
    CR[dt] = {x['ticker']: x.get('composite_rank', x.get('rank', 999)) for x in r}
    dts.append(dt)
dts = sorted(dts)

try:
    sys.path.insert(0, R)
    from breadth_diagnostic import breadth_scale_by_date as _bsbd
    BRD = _bsbd(list(dts))
except Exception as e:
    BRD = {}
    print(f"브레드스 미로드({e})")

reg = {}; md = True; stk = 0; ss = None
for dd in dts:
    ts = pd.Timestamp(dd[:4] + '-' + dd[4:6] + '-' + dd[6:])
    if ts not in kc.index or pd.isna(ma80.get(ts, np.nan)):
        reg[dd] = md; continue
    s = bool(ma20[ts] > ma80[ts]); stk = stk + 1 if s == ss else 1; ss = s
    if stk >= 5 and md != s: md = s
    reg[dd] = md

def pxv(t, d):
    return parr[tdi[d], pcol[t]] if (t in pcol and d in tdi) else None

# 섹터 맵
try:
    sm = pd.read_parquet(R + '/data_cache/ksic_sector_map.parquet')
    print("섹터맵 컬럼:", list(sm.columns), "행:", len(sm))
    tcol = [c for c in sm.columns if 'tick' in c.lower() or '종목' in c or 'code' in c.lower()]
    scol = [c for c in sm.columns if 'sector' in c.lower() or '섹터' in c or '업종' in c]
    if tcol and scol:
        SEC = dict(zip(sm[tcol[0]].astype(str).str.zfill(6), sm[scol[0]]))
    else:
        SEC = dict(zip(sm.index.astype(str).str.zfill(6) if sm.index.dtype == object else sm.iloc[:, 0].astype(str).str.zfill(6), sm.iloc[:, -1]))
    print("섹터맵 로드:", len(SEC), "예:", list(SEC.items())[:3])
except Exception as e:
    SEC = {}
    print(f"섹터맵 실패({e})")

# ===== 리플레이: 일별 (raw수익, 브레드스스케일, 보유종목튜플) 생성 =====
E, X, S = 3, 5, 3
port = set(); prev = None
rows = []  # d, raw_ret, brd_scale, holdings(tuple), boost
for i, d0 in enumerate(dts):
    avg = 0.0
    if port and prev:
        rr = [pxv(t, d0) / pxv(t, prev) - 1 for t in port
              if pxv(t, prev) and pxv(t, d0) and pxv(t, prev) > 0 and pxv(t, d0) > 0]
        avg = np.mean(rr) if rr else 0.0
    rows.append([d0, avg, BRD.get(d0, 1.0), tuple(sorted(port)), reg.get(d0, True)])
    if i < 2:
        prev = d0; continue
    d1, d2 = dts[i - 1], dts[i - 2]
    if not reg.get(d0, True):
        port = set(); prev = d0; continue
    if reg.get(dts[i - 1], True) != reg.get(d0, True):
        port.clear()
    a0, a1, a2 = CR[d0], CR[d1], CR[d2]
    wr = lambda t: a0.get(t, 50) * 0.4 + a1.get(t, 50) * 0.35 + a2.get(t, 50) * 0.25
    port = {t for t in port if wr(t) <= X}
    t20 = lambda a: {t for t, r in a.items() if r <= 20}
    for t in sorted(t20(a0) & t20(a1) & t20(a2), key=wr):
        if len(port) >= S: break
        if wr(t) <= E: port.add(t)
    prev = d0

D = pd.DataFrame(rows, columns=['d', 'raw', 'brd', 'hold', 'boost'])

def perf(rets, sub=None, dates=None):
    a = np.asarray(rets, dtype=float)
    if sub is not None and dates is not None:
        mask = (dates >= sub[0]) & (dates <= sub[1])
        a = a[mask]
    if len(a) < 20: return 0, 0, 0
    eq = np.cumprod(1 + a); peak = np.maximum.accumulate(eq)
    mdd = ((eq - peak) / peak).min() * 100
    cagr = (eq[-1] ** (252 / len(a)) - 1) * 100
    return cagr, mdd, (cagr / abs(mdd) if mdd < 0 else 0)

dates = D['d'].values
P1 = ('20190102', '20211231'); P2 = ('20220101', '20231231'); P3 = ('20240101', '20261231')

def report(name, rets):
    c, m, cal = perf(rets)
    _, _, a = perf(rets, P1, dates); _, _, b = perf(rets, P2, dates); _, _, cc = perf(rets, P3, dates)
    print(f"  {name:34s} Cal {cal:5.2f}  강세 {a:5.2f}  약세 {b:5.2f}  최근 {cc:5.2f}  MDD {m:6.1f}  CAGR {c:6.1f}")

base = (D['raw'] * D['brd']).values
print("\n===== baseline =====")
report('현행 (브레드스만)', base)

# ===== 2026-02-27~03-04 급락 당시 보유종목 확인 =====
print("\n[2026-02/03 급락 당시 보유]")
for d in ['20260226', '20260227', '20260302', '20260303', '20260304', '20260323', '20260327', '20260331']:
    row = D[D['d'] == d]
    if len(row):
        h = row['hold'].iloc[0]
        secs = [SEC.get(t, '?') for t in h]
        print(f"  {d}: ret {row['raw'].iloc[0]*100:6.2f}%  {list(zip(h, secs))}")

# ===== A) 섹터 쏠림 스케일 =====
print("\n===== A) 섹터 쏠림 스케일 (3슬롯 전부 동일섹터 → 노출축소, 선택불변) =====")
same_sector = D['hold'].apply(lambda h: len(h) == 3 and SEC and len({SEC.get(t, t) for t in h}) == 1)
print(f"  3슬롯 동일섹터 일수: {same_sector.sum()}/{(D['hold'].apply(len)==3).sum()} (전체 {len(D)})")
# 판단은 전일 보유(오늘 수익은 전일 보유로 발생) → hold는 당일 리밸 후. 전일 hold 기준으로 당일 스케일.
sig = same_sector.shift(1).fillna(False)
for sc in [0.75, 0.5]:
    scale = np.where(sig, sc, 1.0)
    report(f'동일섹터→×{sc}', D['raw'].values * D['brd'].values * scale)

# ===== B) 쇼크 브레이크 =====
print("\n===== B) 쇼크 브레이크 (전일 포트수익 < -X% → N일 노출 50%) =====")
pr = D['raw'].values * D['brd'].values  # 실제 겪는 수익
for thr in [-0.04, -0.06, -0.08]:
    for N in [1, 2, 3]:
        scale = np.ones(len(D))
        cool = 0
        for i in range(1, len(D)):
            if pr[i - 1] < thr: cool = N
            if cool > 0: scale[i] = 0.5; cool -= 1
        report(f'shock<{thr*100:.0f}% → {N}일 50%', D['raw'].values * D['brd'].values * scale)

# ===== C) 포트 변동성 타게팅 =====
print("\n===== C) 변동성 타게팅 (20일 실현변동성, 상한 1.0) =====")
s = pd.Series(pr)
rv = s.rolling(20).std().shift(1)  # 전일까지
for tgt in [0.02, 0.025, 0.03]:
    scale = (tgt / rv).clip(upper=1.0).fillna(1.0).values
    report(f'vol타겟 일{tgt*100:.1f}%', D['raw'].values * D['brd'].values * scale)
