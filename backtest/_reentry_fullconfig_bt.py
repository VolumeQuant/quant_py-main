# -*- coding: utf-8 -*-
"""비대칭 재진입 full-config 최종검증 (2026-06-14).
★TurboSim(4팩터 재계산) 대신 저장된 production wr(과열캡·신팩터·페널티 다 포함)을
그대로 써서 E3X6S3 슬롯 + regime 직접 replay. 5일 vs 2일 재진입 + WF.
"""
import sys, io, os, glob, json
import numpy as np, pandas as pd
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# production boost 랭킹 (wr = 오버레이 다 포함된 production 값)
rk = {}
for f in sorted(glob.glob(os.path.join(PROJ, 'state', 'ranking_2019*.json'))
              + glob.glob(os.path.join(PROJ, 'state', 'ranking_202[0-6]*.json'))):
    dt = os.path.basename(f).replace('ranking_', '').replace('.json', '')
    if dt < '20190102':
        continue
    try:
        d = json.load(open(f, encoding='utf-8'))
        rk[dt] = {x['ticker']: x['weighted_rank'] for x in d['rankings']}
    except Exception:
        pass
dates = sorted(rk)
px = pd.read_parquet(sorted(glob.glob(os.path.join(PROJ, 'data_cache', 'all_ohlcv_*.parquet')),
                            key=lambda f: f.split('_')[-1])[-1]).replace(0, np.nan).sort_index()
pxidx = {d: pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]) for d in dates}
print(f'[데이터] {dates[0]}~{dates[-1]} {len(dates)}일 (production wr replay)')

kc = pd.read_parquet(os.path.join(PROJ, 'data_cache', 'kospi_yf.parquet')).iloc[:, 0]
ma20, ma80 = kc.rolling(20).mean(), kc.rolling(80).mean()

def calc_reg(exit_confirm=5, entry_confirm=5, dsub=None):
    ds = dsub or dates
    reg = {}; md = True; stk = 0; ss = None
    for d in ds:
        ts = pxidx[d]
        if ts not in kc.index or pd.isna(ma80.get(ts, np.nan)):
            reg[d] = md; continue
        s = bool(ma20[ts] > ma80[ts])
        if s == ss: stk += 1
        else: stk = 1; ss = s
        need = entry_confirm if s else exit_confirm
        if stk >= need and md != s: md = s
        reg[d] = md
    return reg

def ret1(tk, d, dn):
    if tk not in px.columns: return None
    s = px[tk]; a, b = s.get(pxidx[d]), s.get(pxidx[dn])
    if a is None or b is None or pd.isna(a) or pd.isna(b) or a <= 0: return None
    r = b/a - 1
    return None if abs(r) > 0.35 else r  # 분할 아티팩트 제외

def replay(reg, dsub=None, weights=None):
    ds = dsub or dates
    hold = set(); rets = []
    for i in range(len(ds)-1):
        d, dn = ds[i], ds[i+1]
        if not reg[d]:            # defense = 현금
            hold = set(); rets.append(0.0); continue
        rank = rk[d]
        hold = {t for t in hold if rank.get(t, 9999) <= 6}      # X6 청산
        if len(hold) < 3:                                       # E3 진입 (3슬롯)
            for t in sorted([t for t in rank if rank[t] <= 3 and t not in hold], key=lambda t: rank[t]):
                if len(hold) >= 3: break
                hold.add(t)
        # 비중: weights None=균등, 아니면 wr 좋은 순으로 weights 배분
        hs = sorted(hold, key=lambda t: rank.get(t, 9999))
        pairs = [(t, ret1(t, d, dn)) for t in hs]
        pairs = [(t, r) for t, r in pairs if r is not None]
        if not pairs:
            rets.append(0.0); continue
        if weights:
            w = np.array(weights[:len(pairs)], dtype=float); w /= w.sum()
            rets.append(float(sum(w[k]*pairs[k][1] for k in range(len(pairs)))))
        else:
            rets.append(float(np.mean([r for _, r in pairs])))
    return np.array(rets)

def metrics(rets):
    eq = np.cumprod(1+rets); n = len(rets)
    cagr = (eq[-1]**(252/max(n, 1))-1)*100
    peak = np.maximum.accumulate(np.concatenate([[1.0], eq]))
    mdd = abs(((np.concatenate([[1.0], eq])-peak)/peak).min())*100
    return cagr, mdd, (cagr/mdd if mdd > 0 else 0)

print('\n========== full-config 비대칭 재진입 (production wr, E3X6S3) ==========')
print(f"{'재진입':>8}{'Calmar':>9}{'CAGR':>8}{'MDD':>8}")
for ec in [5, 3, 2, 1]:
    cg, md, cal = metrics(replay(calc_reg(5, ec)))
    tag = ' ← 현행' if ec == 5 else ''
    print(f"{ec:>7}일{cal:>9.3f}{cg:>8.1f}{md:>8.1f}{tag}")

print('\n  [WF] 5일 vs 2일 기간분할 (full-config)')
for nm, lo, hi in [('2019-21', '20190102', '20211231'), ('2022-23', '20220101', '20231231'), ('2024-26', '20240101', '20261231')]:
    dsub = [d for d in dates if lo <= d <= hi]
    if len(dsub) < 30: continue
    r5 = metrics(replay(calc_reg(5, 5, dsub), dsub))[2]
    r2 = metrics(replay(calc_reg(5, 2, dsub), dsub))[2]
    print(f"   {nm}: 5일 {r5:.2f} → 2일 {r2:.2f}  (Δ{r2-r5:+.2f})")

# ===== 슬롯 비중 (1:1:1 vs 5:3:2 등) full-config =====
print('\n========== 슬롯 비중 (wr 1·2·3위에 비중 차등, 현행 5일 재진입) ==========')
reg5 = calc_reg(5, 5)
print(f"{'비중(1:2:3위)':>14}{'Calmar':>9}{'CAGR':>8}{'MDD':>8}")
for nm, w in [('1:1:1 (균등·현행)', [1, 1, 1]), ('5:3:2', [5, 3, 2]), ('4:3:3', [4, 3, 3]),
              ('6:3:1', [6, 3, 1]), ('2:1:1', [2, 1, 1]), ('1:1:2 (역가중)', [1, 1, 2])]:
    cg, md, cal = metrics(replay(reg5, weights=w))
    tag = ' ← 현행' if nm.startswith('1:1:1') else ''
    print(f"{nm:>14}{cal:>9.3f}{cg:>8.1f}{md:>8.1f}{tag}")

# WF: 균등 vs 5:3:2 vs 1:1:2(역가중)
print('\n  [WF] 균등(1:1:1) vs 5:3:2 vs 1:1:2(역가중) 기간분할')
for nm, lo, hi in [('2019-21', '20190102', '20211231'), ('2022-23', '20220101', '20231231'), ('2024-26', '20240101', '20261231')]:
    dsub = [d for d in dates if lo <= d <= hi]
    if len(dsub) < 30: continue
    re = calc_reg(5, 5, dsub)
    eq = metrics(replay(re, dsub))[2]
    w532 = metrics(replay(re, dsub, weights=[5, 3, 2]))[2]
    w112 = metrics(replay(re, dsub, weights=[1, 1, 2]))[2]
    print(f"   {nm}: 균등 {eq:.2f} | 5:3:2 {w532:.2f}(Δ{w532-eq:+.2f}) | 1:1:2 {w112:.2f}(Δ{w112-eq:+.2f})")

# ★인접안정성: 1:1:2 주변 (1:1:2만 튄건가, plateau인가)
print('\n  [인접안정성] 역가중 주변 (3위 비중 1.0~3.0) — 1:1:2가 spike인가 plateau인가')
reg5 = calc_reg(5, 5)
cals = []
for w3 in [1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]:
    cal = metrics(replay(reg5, weights=[1, 1, w3]))[2]
    cals.append(cal)
    print(f"   1:1:{w3}: Cal {cal:.3f}")
cv = np.std(cals) / np.mean(cals)
print(f"   → 인접 CV {cv:.3f} (CLAUDE 기준 <0.10~0.30 = 안정), 단조증가면 plateau")
