# -*- coding: utf-8 -*-
"""2026-07-04 심층 EDA — 현행 E3X5S3+브레드스 faithful 리플레이 기반.
1) MDD 해부(에피소드별 날짜·보유종목·국면/브레드스 상태)
2) 슬롯 미충족(underfill) 분포 + 그 기간 수익 특성
3) 거래 통계 갱신(X5 체제)
_fastexit_faithful.py 하니스 복제."""
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
print(f"state 일수: {len(dts)} ({dts[0]} ~ {dts[-1]})")

try:
    sys.path.insert(0, R)
    from breadth_diagnostic import breadth_scale_by_date as _bsbd
    BRD = _bsbd(list(dts))
    print(f"브레드스 스케일 로드: {sum(1 for v in BRD.values() if v < 1.0)}일 발동")
except Exception as e:
    BRD = {}
    print(f"브레드스 미로드({e}) — 스케일 1.0")

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

# ===== 상세 리플레이 (현행 E3 X5 S3, 브레드스 ON) =====
E, X, S = 3, 5, 3
port = {}          # ticker -> {'entry_d':, 'entry_px':}
prev = None
daily = []          # (date, ret_scaled, nslots, regime, brd)
trades = []         # closed trades
slotlog = []
for i, d0 in enumerate(dts):
    avg = 0.0
    if port and prev:
        rr = [pxv(t, d0) / pxv(t, prev) - 1 for t in port
              if pxv(t, prev) and pxv(t, d0) and pxv(t, prev) > 0 and pxv(t, d0) > 0]
        avg = np.mean(rr) if rr else 0.0
    sc = BRD.get(d0, 1.0)
    daily.append((d0, avg * sc, len(port), reg.get(d0, True), sc))
    if i < 2:
        prev = d0; continue
    d1, d2 = dts[i - 1], dts[i - 2]
    if not reg.get(d0, True):
        for t, info in port.items():
            p = pxv(t, d0)
            trades.append({'t': t, 'entry_d': info['entry_d'], 'exit_d': d0,
                           'ret': (p / info['entry_px'] - 1) if (p and info['entry_px']) else np.nan,
                           'reason': 'regime'})
        port = {}; prev = d0; continue
    if reg.get(dts[i - 1], True) != reg.get(d0, True):
        for t, info in port.items():
            p = pxv(t, d0)
            trades.append({'t': t, 'entry_d': info['entry_d'], 'exit_d': d0,
                           'ret': (p / info['entry_px'] - 1) if (p and info['entry_px']) else np.nan,
                           'reason': 'regime_flip'})
        port = {}
    a0, a1, a2 = CR[d0], CR[d1], CR[d2]
    def wr(t):
        return a0.get(t, 50) * 0.4 + a1.get(t, 50) * 0.35 + a2.get(t, 50) * 0.25
    # 이탈
    for t in list(port.keys()):
        if wr(t) > X:
            p = pxv(t, d0)
            info = port.pop(t)
            trades.append({'t': t, 'entry_d': info['entry_d'], 'exit_d': d0,
                           'ret': (p / info['entry_px'] - 1) if (p and info['entry_px']) else np.nan,
                           'reason': 'rank_exit'})
    # 진입
    t20 = lambda a: {t for t, r in a.items() if r <= 20}
    common = t20(a0) & t20(a1) & t20(a2)
    for t in sorted(common, key=wr):
        if len(port) >= S: break
        if t not in port and wr(t) <= E:
            port[t] = {'entry_d': d0, 'entry_px': pxv(t, d0)}
    slotlog.append((d0, len(port), reg.get(d0, True)))
    prev = d0

df = pd.DataFrame(daily, columns=['d', 'ret', 'nslots', 'boost', 'brd'])
df['eq'] = (1 + df['ret']).cumprod()
df['peak'] = df['eq'].cummax()
df['dd'] = df['eq'] / df['peak'] - 1
n = len(df)
cagr = (df['eq'].iloc[-1] ** (252 / n) - 1) * 100
mdd = df['dd'].min() * 100
print(f"\n[baseline 재현] CAGR {cagr:.1f}%  MDD {mdd:.1f}%  Calmar {cagr/abs(mdd):.2f}")

# ===== 1) MDD 해부 — 상위 5개 드로다운 에피소드 =====
print("\n===== 1) 드로다운 에피소드 해부 (고점→저점→회복) =====")
epis = []
in_dd = False
for idx, row in df.iterrows():
    if row['dd'] < -0.005 and not in_dd:
        in_dd = True; start = idx; trough = idx; tval = row['dd']
    elif in_dd:
        if row['dd'] < tval: trough = idx; tval = row['dd']
        if row['dd'] >= -1e-9:
            epis.append((start, trough, idx, tval)); in_dd = False
if in_dd: epis.append((start, trough, len(df) - 1, tval))
epis.sort(key=lambda x: x[3])
for st, tr, en, tv in epis[:6]:
    d_st, d_tr, d_en = df['d'].iloc[st], df['d'].iloc[tr], df['d'].iloc[en]
    dur = tr - st; rec = en - tr
    # 저점까지 구간에서 가장 많이 깎은 종목
    seg = df.iloc[st:tr + 1]
    boostdays = int(seg['boost'].sum()); brddays = int((seg['brd'] < 1).sum())
    print(f"  {tv*100:6.1f}%  {d_st}→{d_tr}(저점,{dur}d)→{d_en}(회복,{rec}d)  boost일 {boostdays}/{len(seg)}  브레드스발동 {brddays}")

# 최대 에피소드의 일별 기여 상세
st, tr, en, tv = epis[0]
print(f"\n  [최대 MDD 에피소드 {df['d'].iloc[st]}~{df['d'].iloc[tr]} 상세 — 최악 낙폭일 10개]")
seg = df.iloc[st:tr + 1].copy()
worst = seg.nsmallest(10, 'ret')
for _, r in worst.iterrows():
    print(f"    {r['d']}  ret {r['ret']*100:6.2f}%  slots {int(r['nslots'])}  boost {r['boost']}  brd {r['brd']:.1f}")

# ===== 2) 슬롯 미충족 분석 =====
print("\n===== 2) 슬롯 충족 분포 (boost 국면 한정) =====")
sl = pd.DataFrame(slotlog, columns=['d', 'n', 'boost'])
bl = sl[sl['boost']]
dist = bl['n'].value_counts().sort_index()
for k, v in dist.items():
    print(f"  {k}슬롯: {v}일 ({v/len(bl)*100:.1f}%)")
# underfill 날들의 다음날 수익 vs full 날
df2 = df[df['boost']].copy()
df2['ret_next'] = df['ret'].shift(-1)
for cond, lbl in [(df2['nslots'] < 3, '슬롯<3'), (df2['nslots'] == 3, '슬롯=3')]:
    sub = df2[cond & (df2['nslots'] > 0)]
    if len(sub):
        print(f"  {lbl}: {len(sub)}일, 당일평균 {sub['ret'].mean()*100:.3f}%, 일변동성 {sub['ret'].std()*100:.2f}%")
z = df2[df2['nslots'] == 0]
print(f"  슬롯=0 (boost인데 빈 포트): {len(z)}일")

# ===== 3) 거래 통계 (X5 체제) =====
print("\n===== 3) 거래 통계 =====")
tdf = pd.DataFrame(trades).dropna(subset=['ret'])
tdf['hold'] = tdf.apply(lambda r: tdi[r['exit_d']] - tdi[r['entry_d']], axis=1)
print(f"  총 {len(tdf)}건  승률 {(tdf['ret']>0).mean()*100:.0f}%  평균 {tdf['ret'].mean()*100:+.2f}%  중앙 {tdf['ret'].median()*100:+.2f}%")
w = tdf[tdf['ret'] > 0]; l = tdf[tdf['ret'] <= 0]
print(f"  승 평균 {w['ret'].mean()*100:+.1f}% (보유중앙 {w['hold'].median():.0f}d) / 패 평균 {l['ret'].mean()*100:+.1f}% (보유중앙 {l['hold'].median():.0f}d)")
print(f"  손익비 {abs(w['ret'].mean()/l['ret'].mean()):.2f}  수익합 상위5% 거래 기여 {tdf.nlargest(max(1,len(tdf)//20),'ret')['ret'].sum()/tdf['ret'].sum()*100:.0f}%")
print(f"  이탈사유: {tdf['reason'].value_counts().to_dict()}")
# 연도별
tdf['yr'] = tdf['exit_d'].str[:4]
print("\n  연도별 거래:")
for yr, g in tdf.groupby('yr'):
    print(f"    {yr}: {len(g)}건 승률 {(g['ret']>0).mean()*100:.0f}% 평균 {g['ret'].mean()*100:+.1f}%")
