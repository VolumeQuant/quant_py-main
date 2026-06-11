# -*- coding: utf-8 -*-
"""일자별 state 심층 분석 — top3 신호가 올해 실제로 작동했나 실증.
1) live-replay: 매일 top3(wr) 균등보유 누적수익 vs KOSPI
2) "이미 오른 걸 사나" 검증: 진입시 직전60일 수익 vs 진입후 20일 수익
3) 현재 top3(제주·SK·디바이스) 궤적 견고성
4) top3 이탈 종목의 이후 수익 (시스템이 손실 회피하나)
"""
import sys, io, glob, json
import numpy as np, pandas as pd
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# --- 데이터 로드 ---
px = pd.read_parquet(sorted(glob.glob('data_cache/all_ohlcv_20190603_*.parquet'))[-1]).sort_index()
kospi = pd.read_parquet('data_cache/kospi_yf.parquet')
files = sorted(glob.glob('state/ranking_2026*.json'))
day_top = {}   # date -> [(pos,ticker,name,wr,M,score,per,pbr)]
nm = {}
for f in files:
    d = json.load(open(f, encoding='utf-8'))
    r = sorted(d['rankings'], key=lambda x: (x['weighted_rank'], x['composite_rank']))
    day_top[d['date']] = r
    for x in r: nm[x['ticker']] = x['name']
dates = sorted(day_top)
pxdates = list(px.index)
def pxidx(yyyymmdd):
    ts = pd.Timestamp(yyyymmdd[:4]+'-'+yyyymmdd[4:6]+'-'+yyyymmdd[6:])
    pos = px.index.searchsorted(ts)
    return pos if pos < len(px.index) and px.index[pos] == ts else (pos if pos < len(px.index) else None)

SPLIT = 0.35  # 한국 일일 등락 ±30% → 그 이상 점프는 분할/오류로 간주

def _clean_window(ticker, i, j):
    """px[ticker] i..j 구간이 분할/0원/NaN 없이 깨끗하면 (a,b) 반환, 아니면 None."""
    if ticker not in px.columns: return None
    s = px[ticker]
    if i < 0 or j >= len(s) or i == j: return None
    seg = s.iloc[min(i,j):max(i,j)+1]
    if seg.isna().any() or (seg <= 0).any(): return None
    dc = seg.pct_change().dropna()
    if (dc.abs() > SPLIT).any(): return None   # 분할/이상치 포함 → 신뢰불가
    return s.iloc[i], s.iloc[j]

def _idx(yyyymmdd):
    ts = pd.Timestamp(yyyymmdd[:4]+'-'+yyyymmdd[4:6]+'-'+yyyymmdd[6:])
    i = px.index.searchsorted(ts)
    return i if (i < len(px.index) and px.index[i] == ts) else None

def fwd_ret(ticker, yyyymmdd, n):
    i = _idx(yyyymmdd)
    if i is None: return None
    r = _clean_window(ticker, i, i+n)
    return None if r is None else (r[1]/r[0]-1)*100

def trail_ret(ticker, yyyymmdd, n):
    i = _idx(yyyymmdd)
    if i is None: return None
    r = _clean_window(ticker, i-n, i)
    return None if r is None else (r[1]/r[0]-1)*100

# === 1. LIVE-REPLAY: 매일 top3 균등보유 (다음날 종가 수익 누적) ===
print('=== 1. top3 균등보유 live-replay (올해, 일별 리밸런스 근사) ===')
port = 1.0; bench = 1.0; rets = []; brets = []
ks = kospi.iloc[:,0] if kospi.shape[1]>=1 else kospi['Close']
for i in range(len(dates)-1):
    dt = dates[i]
    top3 = [x['ticker'] for x in day_top[dt][:3]]
    r1 = [fwd_ret(t, dt, 1) for t in top3]
    r1 = [x for x in r1 if x is not None]
    if not r1: continue
    dr = np.mean(r1)/100
    port *= (1+dr); rets.append(dr)
    # KOSPI 같은 구간
    ts0 = pd.Timestamp(dt[:4]+'-'+dt[4:6]+'-'+dt[6:])
    j = ks.index.searchsorted(ts0)
    if j+1 < len(ks) and j < len(ks):
        bdr = ks.iloc[j+1]/ks.iloc[j]-1; bench*=(1+bdr); brets.append(bdr)
rets = np.array(rets)
ann_days = 252
cum = port-1; mdd = 0; peak=1; eq=1
for r in rets:
    eq*=(1+r); peak=max(peak,eq); mdd=min(mdd, eq/peak-1)
print(f'  top3 누적: {cum*100:+.1f}%  (KOSPI {(bench-1)*100:+.1f}%)')
print(f'  일변동성: {rets.std()*100:.2f}%/일, 연환산 {rets.std()*np.sqrt(252)*100:.0f}%')
print(f'  MDD(일별 근사): {mdd*100:.1f}%  | 승률(상승일) {100*np.mean(rets>0):.0f}%')
print(f'  Sharpe 근사(무위험0): {rets.mean()/rets.std()*np.sqrt(252):.2f}')

# === 2. "이미 오른 걸 사나" — 진입시 직전수익 vs 진입후 수익 ===
print('\n=== 2. top3 "고점 추격" 검증 (직전 60일 vs 이후 20일) ===')
pairs = []
for dt in dates:
    for x in day_top[dt][:3]:
        tr = trail_ret(x['ticker'], dt, 60); fr = fwd_ret(x['ticker'], dt, 20)
        if tr is not None and fr is not None: pairs.append((tr, fr))
pairs = np.array(pairs)
print(f'  관측 {len(pairs)}건. 진입시 직전60일 평균 {pairs[:,0].mean():+.1f}%, 이후20일 평균 {pairs[:,1].mean():+.1f}%')
print(f'  이후20일 승률 {100*np.mean(pairs[:,1]>0):.0f}%')
# 직전수익 사분위별 이후수익 (높이 오른 걸 살수록 이후가 나쁜가?)
q = np.quantile(pairs[:,0],[0,.25,.5,.75,1.0])
for lo,hi,lab in [(q[0],q[1],'덜 오름(하위25%)'),(q[1],q[2],'25-50%'),(q[2],q[3],'50-75%'),(q[3],q[4],'많이 오름(상위25%)')]:
    m = pairs[(pairs[:,0]>=lo)&(pairs[:,0]<=hi)]
    print(f'    직전 {lab} (직전 {lo:+.0f}~{hi:+.0f}%): 이후20일 평균 {m[:,1].mean():+.1f}% 승률{100*np.mean(m[:,1]>0):.0f}%')

# === 3. 현재 top3 궤적 견고성 ===
print('\n=== 3. 현재 top3 궤적 (최근 20일 wr 순위) ===')
cur3 = [x['ticker'] for x in day_top[dates[-1]][:3]]
for t in cur3:
    traj = []
    for dt in dates[-20:]:
        r = day_top[dt]; pos = next((i+1 for i,x in enumerate(r) if x['ticker']==t), None)
        traj.append(str(pos) if pos and pos<=30 else '·')
    print(f'  {nm[t]:<10}({t}) 최근20일 순위: {" ".join(traj)}')

# === 4. top3 이탈 종목의 이후 수익 (손실 회피?) ===
print('\n=== 4. top3에서 빠진 직후 20일 수익 (시스템이 고점 탈출하나) ===')
exits = []
for i in range(1,len(dates)):
    prev = set(x['ticker'] for x in day_top[dates[i-1]][:3])
    now = set(x['ticker'] for x in day_top[dates[i]][:3])
    for t in (prev-now):
        fr = fwd_ret(t, dates[i], 20)
        if fr is not None: exits.append((nm.get(t,t), dates[i], fr))
if exits:
    arr = np.array([e[2] for e in exits])
    print(f'  이탈 {len(exits)}건. 이탈 후 20일 평균 {arr.mean():+.1f}% 승률{100*np.mean(arr>0):.0f}%')
    print('  (양수=빠진 뒤에도 올랐다=조기이탈 / 음수=빠진 게 정답)')
    for n_,d_,r_ in exits[-8:]: print(f'    {d_} {n_} 이탈후20일 {r_:+.1f}%')
