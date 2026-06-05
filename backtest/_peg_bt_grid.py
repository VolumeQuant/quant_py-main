"""pen_cs W-그리드 BT (production-replay, baked composite_rank 기반).
cr(W) = rank(score + W*overheat_pen) per date. W=0 = v80.22 baseline.
production 로직: MA20x80x5 국면, wr=0.4cr0+0.35cr1+0.25cr2(Top20 밖 penalty50),
진입 rank<=3(boost)/0(defense), 이탈 wr>4(boost)/8, 슬롯3, SL/TS 없음 (v80.22).
LOO: 단일 슈퍼위너 제외 robustness.
"""
import sys, json, time, glob
from pathlib import Path
from collections import defaultdict
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')

DATA = Path('data_cache')
STATE = Path('backtest/state_peg_bt')
PENALTY = 50; TOP_N = 20
EB = 3; SLOTS = 3; XB = 4          # v80.22 boost: entry<=3, exit wr>4, slots 3
DEF_EB = 0; DEF_XB = 8

ohlcv = pd.read_parquet(sorted(DATA.glob('all_ohlcv_2017*_*.parquet'))[-1]).replace(0, np.nan)
ohlcv.index = pd.to_datetime(ohlcv.index)
kospi = pd.read_parquet(str(DATA/'kospi_yf.parquet'))['close'].sort_index()

def regime_cross(dates, short=20, lp=80, cf=5):
    sma = kospi.rolling(short).mean(); lma = kospi.rolling(lp).mean()
    reg = {}; md = False; stk = 0; ss = None
    for d in dates:
        ts = pd.Timestamp(d); sv = sma.get(ts); lv = lma.get(ts)
        if sv is None or pd.isna(sv) or pd.isna(lv): reg[d] = md; continue
        s = sv > lv
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= cf and md != s: md = s
        reg[d] = md
    return reg

def gp(d, tk):
    ts = pd.Timestamp(d)
    if ts not in ohlcv.index:
        idx = ohlcv.index.searchsorted(ts)
        if idx >= len(ohlcv): return None
        ts = ohlcv.index[idx]
    if tk not in ohlcv.columns: return None
    v = ohlcv.loc[ts, tk]
    return v if pd.notna(v) and v > 0 else None

# --- load all rankings once: date -> list of (tk, score, pen) ---
print('랭킹 로드...', flush=True)
RAW = {}
for fp in sorted(STATE.glob('ranking_*.json')):
    ds = fp.stem.replace('ranking_', '')
    if not (ds.isdigit() and len(ds) == 8): continue
    if not ('20190102' <= ds <= '20260529'): continue
    d = json.load(open(fp, encoding='utf-8'))
    rows = d.get('rankings', [])
    RAW[ds] = [(str(r['ticker']).zfill(6), r.get('score', 0.0) or 0.0,
                r.get('overheat_pen', 0.0) or 0.0, r.get('composite_rank', r.get('rank', 999)))
               for r in rows]
ADATES = sorted(RAW.keys())
print(f'  {len(ADATES)}일 ({ADATES[0]}~{ADATES[-1]})', flush=True)

def cr_for_W(W, exclude=None):
    """date -> {tk: rank} by score+W*pen desc."""
    crc = {}
    for d, rows in RAW.items():
        items = [(tk, sc + W*pen) for (tk, sc, pen, cr0) in rows if not (exclude and tk in exclude)]
        items.sort(key=lambda x: -x[1])
        crc[d] = {tk: i+1 for i, (tk, _) in enumerate(items)}
    return crc

def run(dates, regime, crc):
    pf = {}; eq = 1.0; eh = {}
    turn = 0
    for i, d in enumerate(dates):
        ib = regime.get(d, True); er = EB if ib else DEF_EB; xr = XB if ib else DEF_XB
        if i >= 1 and pf:
            rs = []
            for tk in pf:
                pp = gp(dates[i-1], tk); cp = gp(d, tk)
                if pp and cp: rs.append(cp/pp - 1)
            if rs: eq *= (1 + np.mean(rs)*len(pf)/SLOTS)
        eh[d] = eq
        if i >= 1 and regime.get(dates[i-1], True) != ib:
            pf.clear()
        if not ib:
            continue
        cr0 = crc.get(d, {}); cr1 = crc.get(dates[i-1], {}) if i>=1 else {}; cr2 = crc.get(dates[i-2], {}) if i>=2 else {}
        t1 = {tk:c for tk,c in cr1.items() if c <= TOP_N}; t2 = {tk:c for tk,c in cr2.items() if c <= TOP_N}
        wr = {tk: c0*0.4 + t1.get(tk,PENALTY)*0.35 + t2.get(tk,PENALTY)*0.25 for tk,c0 in cr0.items()}
        for tk in list(pf.keys()):
            if wr.get(tk, 999) > xr:
                del pf[tk]; turn += 1
        for tk, _ in sorted(wr.items(), key=lambda x: x[1])[:er]:
            if tk in pf: continue
            if len(pf) >= SLOTS: break
            cp = gp(d, tk)
            if cp: pf[tk] = cp; turn += 1
    ea = np.array(list(eh.values()))
    if len(ea) < 50: return None
    cagr = (ea[-1]**(252/len(ea)) - 1)*100
    p = np.maximum.accumulate(ea); mdd = -((ea-p)/p).min()*100
    cal = cagr/mdd if mdd > 0 else 0
    es = pd.Series(eh)
    wf = []
    for st, ed in [('20190102','20191231'),('20200101','20211231'),('20220101','20231231'),('20240101','20260529')]:
        sub = es[(es.index>=st)&(es.index<=ed)]
        if len(sub) < 50: continue
        sr = (sub.iloc[-1]/sub.iloc[0])**(252/len(sub)) - 1
        sp = np.maximum.accumulate(sub.values); sd = -((sub.values-sp)/sp).min()
        wf.append((sr*100)/(sd*100) if sd > 0 else 0)
    return {'cal':cal,'cagr':cagr,'mdd':mdd,'wfmin':min(wf) if wf else 0,'turn':turn,'final':ea[-1]}

WGRID = [0.0, 0.05, 0.1, 0.15, 0.2, 0.3]
ISD = [d for d in ADATES if d <= '20221231']; OOSD = [d for d in ADATES if d >= '20230102']
reg_all = regime_cross(ADATES); reg_is = regime_cross(ISD); reg_oos = regime_cross(OOSD)

# W=0 cr vs composite_rank 일치 검증
crc0 = cr_for_W(0.0)
agree = tot = 0
for d, rows in RAW.items():
    for (tk, sc, pen, cr0) in rows:
        if cr0 != 999:
            tot += 1
            if crc0[d].get(tk) == cr0: agree += 1
print(f'\nW=0 cr vs composite_rank 일치: {agree}/{tot} ({agree/tot:.1%})', flush=True)

print(f'\n{"="*72}\n=== pen_cs W-그리드 (production-replay 7.4년) ===\n{"="*72}', flush=True)
print(f'{"W":>6} {"Cal":>7} {"CAGR":>7} {"MDD":>7} {"WFmin":>7} {"IS_Cal":>7} {"OOS_Cal":>8} {"회전":>6}', flush=True)
t0 = time.time()
rows_out = []
for W in WGRID:
    crc = cr_for_W(W)
    full = run(ADATES, reg_all, crc)
    isr = run(ISD, reg_is, {d:crc[d] for d in ISD})
    oosr = run(OOSD, reg_oos, {d:crc[d] for d in OOSD})
    rows_out.append((W, full, isr, oosr))
    mark = ' ←baseline' if W == 0 else ''
    print(f'{W:>6} {full["cal"]:>7.3f} {full["cagr"]:>6.1f}% {full["mdd"]:>6.2f}% {full["wfmin"]:>7.3f} '
          f'{isr["cal"]:>7.3f} {oosr["cal"]:>8.3f} {full["turn"]:>6}{mark}', flush=True)

# Leave-one-out robustness (제룡전기 033100, SK하이닉스 000660 제외)
print(f'\n=== LOO robustness (단일 슈퍼위너 제외) — best W vs baseline ===', flush=True)
base_cal = rows_out[0][1]['cal']
for W in [0.05, 0.1, 0.15]:
    line = f'  W={W}: '
    for loo_name, loo in [('전체',None), ('-033100',{'033100'}), ('-000660',{'000660'}), ('-둘다',{'033100','000660'})]:
        crc = cr_for_W(W, exclude=loo)
        r = run(ADATES, reg_all, crc)
        # baseline 동일 제외
        crcb = cr_for_W(0.0, exclude=loo)
        rb = run(ADATES, reg_all, crcb)
        line += f'{loo_name} Δ{r["cal"]-rb["cal"]:+.3f} '
    print(line, flush=True)
print(f'\n총 {time.time()-t0:.0f}s', flush=True)
