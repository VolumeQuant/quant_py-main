# -*- coding: utf-8 -*-
"""V3: 보유종목 강제매도 누수 감사. 페널티(-W)가 이미 보유한 종목을 exit선(rank>6) 밖으로
밀어내 매도시키는가? 특히 무상증자(호재) 직후면 호재를 토해내는 누수.
방법: with-penalty(W0.3) 포트폴리오 경로를 _run_regime_inner 룰 그대로 재구성+트레이드로그.
각 rank-exit 매도에 대해 no-penalty(W0) wrank 반사실 → 페널티가 원인인지 판정 + 매도후 fwd20d 수익률(누수=양수)."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backtest'))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator
PROJ = os.path.dirname(os.path.abspath(__file__)); DC = os.path.join(PROJ, 'data_cache')
STATE = sys.argv[1] if len(sys.argv) > 1 else 'state'
prices = pd.read_parquet(sorted(glob.glob(os.path.join(DC, 'all_ohlcv_adj_*.parquet')))[-1]).replace(0, np.nan)
kc = pd.read_parquet(os.path.join(DC, 'kospi_yf.parquet')).iloc[:, 0]
ma20 = kc.rolling(20).mean(); ma80 = kc.rolling(80).mean()
G3 = ('rev_z', 'oca_z', 'gp_growth_z', 0.4, 0.4, 0.2)
def calc_reg(ds):
    reg = {}; md = True; stk = 0; ss = None
    for d in ds:
        ts = pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts, np.nan)): reg[d] = md; continue
        s = bool(ma20[ts] > ma80[ts]); stk = stk+1 if s == ss else 1; ss = s
        if stk >= 5 and md != s: md = s
        reg[d] = md
    return reg
ar, days = {}, []
for f in sorted(glob.glob(os.path.join(PROJ, STATE, 'ranking_*.json'))):
    dt = os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt) == 8 and dt >= '20190102':
        ar[dt] = json.load(open(f, encoding='utf-8'))['rankings']; days.append(dt)
days = sorted(days); reg = calc_reg(days)
ca = json.load(open(os.path.join(DC, 'ca_events.json'), encoding='utf-8'))['ca_by_ticker']
nm_by = {x['ticker']: x['name'] for d in days for x in ar[d]}

T = TurboSimulator({d: ar[d] for d in days}, days, prices, overheat_w=0.2); T._use_overlay = True; T._use_stored_growth = True
tks_by_d = {d: T._preextracted[d][0] for d in days}
fd_by_d = {d: {x['ticker']: x for x in ar[d]} for d in days}
base_ov = {d: np.array([0.2*(fd_by_d[d][tk].get('overheat_pen') or 0)+0.05*(fd_by_d[d][tk].get('mom_10_z') or 0)
                        +0.06*(fd_by_d[d][tk].get('vol_low_z') or 0) for tk in tks_by_d[d]]) for d in days}
K = 126
def recent_ca(d, ii, tk):
    cut = days[max(0, ii-K)]; ds = ca.get(tk)
    return bool(ds and any(cut < e <= d for e in ds))
def build_flat(W):
    for ii, d in enumerate(days):
        tks = tks_by_d[d]
        pen = np.array([(-W if (W > 0 and recent_ca(d, ii, tk)) else 0.0) for tk in tks])
        T._overlay_pre[d] = base_ov[d] + pen
    T._cached_key = None
    T._ensure_cache(0.15, 0.0, 0.55, 0.30, 0.4, 20, '12m', *G3[:3], *G3[3:])
    return list(T._cached_flat)
flat_pen = build_flat(0.3)
# no-penalty wrank 맵 (col->wrank) per day
flat0 = build_flat(0.0)
# 반사실 wrank: no-pen flat의 wrank_arr (col 기준), None 가드
nopen_wrank = {i: (flat0[i][0] if flat0[i] is not None else None) for i in range(len(days))}
tk_by_col = {v: k for k, v in T._ticker_to_col.items()} if hasattr(T, '_ticker_to_col') else None

# 포트폴리오 재구성 (with-penalty 경로) — _run_regime_inner 룰: entry<=3, exit>6, 3슬롯, 전환청산
def colname(col):
    return tk_by_col.get(col) if tk_by_col else None
port = {}; prev_reg = None; leaks = []; total_rank_exits = 0
parr = T._price_arr; drows = T._date_row_indices
for i in range(2, len(days)):
    d = days[i]; cur = reg.get(d, False)
    if prev_reg is not None and cur != prev_reg: port = {}
    prev_reg = cur
    if not cur:  # defense=cash
        continue
    if flat_pen[i] is None:
        continue
    wrank_arr, cand_cols, cand_prices, cand_wranks = flat_pen[i]
    npw = nopen_wrank[i]
    # EXIT
    for col in list(port):
        if wrank_arr[col] > 6:  # rank exit
            total_rank_exits += 1
            tk = colname(col); ii = i
            pen_on = recent_ca(d, ii, tk) if tk else False
            np_wr = npw[col] if npw is not None else wrank_arr[col]  # 반사실 no-pen wrank
            caused = pen_on and (np_wr <= 6)  # 페널티 없었으면 보유유지였을 것
            if pen_on:
                # fwd20d 수익률 (매도일 종가 대비)
                cr = drows[i]; fr = drows[min(i+20, len(days)-1)]
                fwd = np.nan
                if cr >= 0 and 0 <= col < parr.shape[1]:
                    p0 = parr[cr, col]; p1 = parr[fr, col]
                    if p0 == p0 and p1 == p1 and p0 > 0: fwd = p1/p0 - 1
                leaks.append((d, tk, nm_by.get(tk, tk), round(float(wrank_arr[col]),2), round(float(np_wr),2), caused, round(float(fwd)*100,1) if fwd==fwd else None))
            del port[col]
    # ENTRY
    slots = 3 - len(port)
    for k in range(len(cand_cols)):
        if slots <= 0: break
        if cand_wranks[k] <= 3 and cand_cols[k] not in port:
            port[cand_cols[k]] = cand_prices[k]; slots -= 1

print(f"[{STATE}] 보유종목 강제매도 누수 감사 (페널티 W0.3 K126)")
print(f"전체 rank-exit 매도: {total_rank_exits}건")
print(f"그중 매도시 CA페널티 발동중(±K): {len(leaks)}건")
caused = [x for x in leaks if x[5]]
print(f"  그중 '페널티가 원인'(반사실 no-pen wrank≤6=원래 보유유지): {len(caused)}건")
if caused:
    fwds = [x[6] for x in caused if x[6] is not None]
    print(f"  페널티원인 매도후 fwd20d 평균 {np.mean(fwds):+.2f}% / 중앙값 {np.median(fwds):+.2f}% (양수=호재토해낸 누수, 음수=회피성공)")
    win = sum(1 for f in fwds if f > 0)
    print(f"  fwd20d 양수(누수) {win}/{len(fwds)}건 ({win/len(fwds)*100:.0f}%)")
    print("  케이스(날짜,종목,pen_wr,nopen_wr,fwd20d%):")
    for x in sorted(caused, key=lambda z: -(z[6] or -99))[:12]:
        print(f"    {x[0]} {x[2]}({x[1]}) wr{x[3]}→반사실{x[4]} fwd{x[6]}%")
print("→ 누수판정: 페널티원인 매도가 적고 fwd20d 평균 음수면 누수 미미(페널티가 옳게 회피)")
