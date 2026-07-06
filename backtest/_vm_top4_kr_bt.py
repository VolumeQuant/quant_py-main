# -*- coding: utf-8 -*-
"""US VM top4 핸드오프 Phase C — KR look-ahead proxy 7.4년 BT (★상한 명시).
구조: 컨센커버 프록시 유니버스 → fwd_PER 게이트 → 리비전(rev90 proxy) 상위 top4 동일가중 → 5거래일 재선발.
프록시: NTM(t) = 실제 TTM(t+250) (완전 컨닝 = look-ahead 상한). rev90(t) = NTM(t)/NTM(t-90) = TTM(t+250)/TTM(t+160).
판정: 위상평균(0~4) + 최악MDD 동반 + 블록(19-21/22-23/24-26) + LOWO 누적. 국면 오버레이(MA20/80 5d) ON 헤드라인.
gap≥2.5는 KR 기각이력(_sleeve_gap_fpe_grid) 있어 참고행만."""
import sys, io, os, glob, json, pickle
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices = pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0, np.nan)
prices = prices[prices.notna().any(axis=1)]
pcol = {c: i for i, c in enumerate(prices.columns)}; parr = prices.values
tdays = [d.strftime('%Y%m%d') for d in prices.index]; tdi = {d: i for i, d in enumerate(tdays)}
NT = len(tdays)
day64 = np.array([np.datetime64(pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])) for d in tdays])
kc = pd.read_parquet(P+'/data_cache/kospi_yf.parquet').iloc[:, 0]
ma20 = kc.rolling(20).mean(); ma80 = kc.rolling(80).mean()
cache = pickle.load(open(P+'/backtest/_earn_cache.pkl', 'rb'))
mc = pd.read_parquet(sorted(glob.glob(P+'/data_cache/market_cap_ALL_*.parquet'))[-1])
sh = {t: mc.loc[t, '상장주식수'] for t in mc.index}

# 시작: 2019-01-02, 끝: NTM 프록시가 t+250 필요 → 마지막 250일은 프록시 부정확(마지막 값 고정). BT 끝 = NT-250
i0 = tdi['20190102']; i_end = NT - 250
dts = tdays[i0:i_end]

# ── 국면 (MA20/80 5일 확인)
reg = {}
md = True; stk = 0; ss = None
for d in tdays:
    ts = pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
    if ts in kc.index and not pd.isna(ma80.get(ts, np.nan)):
        s = bool(ma20[ts] > ma80[ts]); stk = stk+1 if s == ss else 1; ss = s
        if stk >= 5 and md != s: md = s
    reg[d] = md

# ── per-ticker TTM step function (전 거래일 벡터) → NTM/rev/fwd_per/gap 프록시
print("TTM 시계열 전개 중...", flush=True)
TTM = {}     # ticker -> (NT,) array of TTM(지배순이익, 억) as-of each day, nan if <4q
for t, dd in cache.items():
    s = dd.get('ni')
    if s is None or len(s[0]) < 4 or t not in pcol or t not in sh or not sh[t] or sh[t] <= 0: continue
    dts_r, vals = s[0], s[1]
    ttm_at_report = np.full(len(vals), np.nan)
    for k in range(3, len(vals)):
        ttm_at_report[k] = vals[k-3:k+1].sum()
    idx = np.searchsorted(dts_r, day64, side='right') - 1
    arr = np.where(idx >= 0, ttm_at_report[np.clip(idx, 0, None)], np.nan)
    TTM[t] = arr
tickers = sorted(TTM.keys())
print(f"  대상 {len(tickers)}종목", flush=True)

def ntm_i(t, i):  # NTM proxy at day-index i = TTM(i+250)
    return TTM[t][min(i+250, NT-1)]

# ── 리밸일 시그널 계산 (게이트/정렬 재료 전부)
def signals(i):
    """day index i → list of (ticker, fwd_per, rev90, rev60, rev30, gap, mcap)"""
    out = []
    ip = tdi.get(tdays[i]); row = parr[i]
    for t in tickers:
        p = row[pcol[t]]
        if not (p > 0): continue
        mcap = p * sh[t]
        if mcap < 1000e8: continue
        e1 = ntm_i(t, i)
        if not (e1 and e1 > 0): continue
        fpe = mcap / (e1*1e8)
        e90 = TTM[t][min(i+160, NT-1)]   # NTM 90일 전 = TTM(t+160)
        e60 = TTM[t][min(i+190, NT-1)]
        e30 = TTM[t][min(i+220, NT-1)]
        rev90 = e1/e90-1 if (e90 and e90 > 0) else np.nan
        rev60 = e1/e60-1 if (e60 and e60 > 0) else np.nan
        rev30 = e1/e30-1 if (e30 and e30 > 0) else np.nan
        e0 = TTM[t][i]
        gap = e1/e0 if (e0 and e0 > 0) else np.nan   # missing=pass 취지로 nan 유지
        out.append((t, fpe, rev90, rev60, rev30, gap, mcap))
    return out

SIG = {}  # lazy per day-index

def get_sig(i):
    if i not in SIG: SIG[i] = signals(i)
    return SIG[i]

def run(phase, fpe_max=20, sort='rev90', gap_min=None, N=4, R=5, overlay=True,
        excl=frozenset(), top_mcap=None):
    si = {'rev90': 2, 'rev60': 3, 'rev30': 4, 'gap': 5, 'level': 1}[sort]
    held = []; rets = []
    start = tdi['20190102'] + phase
    for j, i in enumerate(range(start, i_end)):
        d = tdays[i]
        r = 0.0
        if held:
            vs = []
            for t in held:
                p0, p1 = parr[i-1, pcol[t]], parr[i, pcol[t]]
                if p0 > 0 and p1 > 0: vs.append(p1/p0-1)
            r = float(np.mean(vs)) if vs else 0.0
        rets.append((d, r))
        if overlay and not reg.get(d, True):
            held = []; continue
        if j % R == 0:
            cands = get_sig(i)
            if top_mcap:
                cands = sorted(cands, key=lambda z: -z[6])[:top_mcap]
            pool = []
            for z in cands:
                if z[0] in excl: continue
                if fpe_max and not (z[1] < fpe_max): continue
                if gap_min is not None and not (np.isnan(z[5]) or z[5] >= gap_min): continue  # missing=pass
                v = -z[1] if sort == 'level' else z[si]
                if not np.isnan(v): pool.append((v, z[0]))
            pool.sort(reverse=True)
            held = [t for _, t in pool[:N]]
    return rets

def stats(rets, sub=None):
    a = np.array([r for d, r in rets if (not sub or sub[0] <= d <= sub[1])])
    if len(a) < 40: return None
    eq = np.cumprod(1+a); peak = np.maximum.accumulate(eq)
    mdd = ((eq-peak)/peak).min()*100
    cagr = (eq[-1]**(252/len(a))-1)*100
    return cagr, mdd, (cagr/abs(mdd) if mdd < 0 else 0)

BLOCKS = [('전체', None), ('강세19-21', ('20190102', '20211231')),
          ('약세22-23', ('20220101', '20231231')), ('최근24-26', ('20240101', '20991231'))]

def report(label, **kw):
    per_phase = [run(ph, **kw) for ph in range(5)]
    line = f"  {label:<34}"
    for bnm, sub in BLOCKS:
        ss = [stats(r, sub) for r in per_phase]
        ss = [s for s in ss if s]
        if not ss: line += f" {'—':>20}"; continue
        cagr = np.mean([s[0] for s in ss]); wmdd = min(s[1] for s in ss)
        calm = np.mean([s[2] for s in ss])
        line += f" {cagr:+7.0f}%/{wmdd:5.1f}/{calm:4.2f}"
    print(line, flush=True)

print("\n[KR VM-top4 look-ahead proxy 7.4y — 위상평균 CAGR% / 최악MDD% / 평균Calmar]")
print("  ※ NTM=실제 미래 TTM 컨닝 = 절대성능 상한. 상대비교(정렬축·게이트)만 유효")
print(f"  {'구성':<34} {'전체':>20} {'강세19-21':>18} {'약세22-23':>18} {'최근24-26':>18}")
report("게이트無 + rev90", fpe_max=None)
report("fwdPER<20 + rev90 ★제안구조", fpe_max=20)
report("fwdPER<25 + rev90", fpe_max=25)
report("fwdPER<30 + rev90", fpe_max=30)
report("fwdPER<20 + rev60", fpe_max=20, sort='rev60')
report("fwdPER<20 + rev30", fpe_max=20, sort='rev30')
report("fwdPER<20 + 레벨정렬(-fwdPER)", fpe_max=20, sort='level')
report("fwdPER<20 + gap정렬(기대성장)", fpe_max=20, sort='gap')
report("[참고] fwdPER<20+gap>=2.5 + rev90", fpe_max=20, gap_min=2.5)
report("fwdPER<20 + rev90, N=3", fpe_max=20, N=3)
report("fwdPER<20 + rev90, N=5", fpe_max=20, N=5)
report("fwdPER<20 + rev90, R=10", fpe_max=20, R=10)
report("fwdPER<20 + rev90, 오버레이OFF", fpe_max=20, overlay=False)
report("fwdPER<20 + rev90, 시총top500", fpe_max=20, top_mcap=500)
