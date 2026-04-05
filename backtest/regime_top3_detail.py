"""Top 3 국면전환 상세 분석"""
import sys, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
sys.path.insert(0, 'backtest')
import pandas as pd, numpy as np
from pathlib import Path
from turbo_simulator import TurboSimulator
from regime_search_v75 import apply_confirmation
from grid_search_v75 import load_bt_rankings, load_prices

CACHE_DIR = Path('data_cache')
all_rankings, dates = load_bt_rankings(Path('backtest/bt_v75'))
prices = load_prices()
bench = pd.read_parquet(CACHE_DIR / 'bench_proxy.parquet')
tsim = TurboSimulator(all_rankings, dates, prices, bench)
ohlcv = prices

phase2b = pd.read_csv('backtest_results/phase2b_rules.csv')
defense_pool = phase2b.nsmallest(200, 'mdd').drop_duplicates(subset=['v','q','g','m','g_rev','mom'], keep='first').head(15)
manual = phase2b[(phase2b.v==20)&(phase2b.q==15)&(phase2b.g==25)&(phase2b.m==40)].nlargest(1,'calmar')
defense_pool = pd.concat([defense_pool, manual]).drop_duplicates(subset=['v','q','g','m','g_rev','mom'])
off_cal = phase2b.nlargest(100, 'calmar').drop_duplicates(subset=['v','q','g','m','g_rev','mom'], keep='first').head(8)
off_cagr = phase2b.nlargest(100, 'cagr').drop_duplicates(subset=['v','q','g','m','g_rev','mom'], keep='first').head(8)
offense_pool = pd.concat([off_cal, off_cagr]).drop_duplicates(subset=['v','q','g','m','g_rev','mom'])

# 브레스
mcap_dict = {f.stem.split('_')[-1]: f for f in sorted(CACHE_DIR.glob('market_cap_ALL_*.parquet'))}
breadth = {}
last_u = None
for d in dates:
    dt = pd.Timestamp(d)
    cands = [k for k in mcap_dict if k <= d]
    if cands:
        mc = pd.read_parquet(mcap_dict[max(cands)])
        u = set(mc[mc['시가총액']/1e8 >= 1000].index) & set(ohlcv.columns)
        last_u = u
    elif last_u: u = last_u
    else: continue
    vc = [t for t in u if t in ohlcv.columns]
    if not vc or dt not in ohlcv.index: continue
    sp = ohlcv.loc[:dt, vc]
    cnt = sp.notna().sum()
    h126 = cnt[cnt >= 126].index.tolist()
    if len(h126) < 10: continue
    s = sp[h126]
    if len(s) < 120: continue
    breadth[d] = (s.iloc[-1] > s.iloc[-120:].mean()).sum() / s.iloc[-1].notna().sum()

kospi = pd.read_parquet(CACHE_DIR / 'kospi_yf.parquet').iloc[:,0]
kosdaq = pd.read_parquet(CACHE_DIR / 'kosdaq_yf.parquet').iloc[:,0]
vix = pd.read_parquet(CACHE_DIR / 'vix_daily.parquet').iloc[:,0]

def pv(series, dt):
    p = series[series.index < dt]
    return float(p.iloc[-1]) if not p.empty and pd.notna(p.iloc[-1]) else None

bp = pd.read_parquet(CACHE_DIR / 'bench_proxy.parquet').iloc[:,0]

top3 = [
    (('V15Q25G15M45', 0.5, '6m'), ('V30Q0G55M15', 0.7, '12m'), 'B126_40', 7),
    (('V20Q20G25M35', 0.3, '6m'), ('V5Q5G70M20', 0.7, '12m'), 'B126_40', 5),
    (('V15Q30G10M45', 0.6, '6m'), ('V5Q5G60M30', 1.0, '6m'), 'KK60+VIX25', 3),
]

for rank, (d_key, o_key, rule_type, cd) in enumerate(top3, 1):
    # 방어 찾기
    dv, dq, dg, dm = [int(x) for x in d_key[0].replace('V','').replace('Q',' ').replace('G',' ').replace('M',' ').split()]
    d_cfg = None
    for _, dc in defense_pool.iterrows():
        if int(dc.v)==dv and int(dc.q)==dq and int(dc.g)==dg and int(dc.m)==dm and dc.g_rev==d_key[1]:
            d_cfg = dc; break

    ov, oq, og, om = [int(x) for x in o_key[0].replace('V','').replace('Q',' ').replace('G',' ').replace('M',' ').split()]
    o_cfg = None
    for _, oc in offense_pool.iterrows():
        if int(oc.v)==ov and int(oc.q)==oq and int(oc.g)==og and int(oc.m)==om and oc.g_rev==o_key[1]:
            o_cfg = oc; break

    if d_cfg is None or o_cfg is None:
        print(f'#{rank}: config not found')
        continue

    # 규칙
    if rule_type == 'B126_40':
        sig = {d: breadth.get(d,0) >= 0.40 for d in dates}
        regime = apply_confirmation(sig, dates, cd)
    elif rule_type == 'KK60+VIX25':
        kp60 = kospi.rolling(60).mean()
        kq60 = kosdaq.rolling(60).mean()
        sig_kk = {}
        for d in dates:
            dt = pd.Timestamp(d)
            k = pv(kospi, dt); km = pv(kp60, dt)
            q = pv(kosdaq, dt); qm = pv(kq60, dt)
            sig_kk[d] = bool(k and km and q and qm and k > km and q > qm)
        regime_kk = apply_confirmation(sig_kk, dates, 3)
        sig_vix = {}
        for d in dates:
            dt = pd.Timestamp(d)
            v = pv(vix, dt)
            sig_vix[d] = bool(v and v < 25)
        regime_vix = apply_confirmation(sig_vix, dates, 1)
        regime = {d: regime_kk.get(d,False) and regime_vix.get(d,False) for d in dates}

    switches = sum(1 for i in range(1, len(dates)) if regime[dates[i]] != regime[dates[i-1]])
    boost_days = sum(1 for d in dates if regime[d])
    years = len(dates) / 252

    d_p = {'v':d_cfg.v/100,'q':d_cfg.q/100,'g':d_cfg.g/100,'m':d_cfg.m/100,
           'g_rev':d_cfg.g_rev,'mom':d_key[2],'entry':int(d_cfg.entry),'exit':d_cfg['exit'],'slots':int(d_cfg.slots)}
    o_p = {'v':o_cfg.v/100,'q':o_cfg.q/100,'g':o_cfg.g/100,'m':o_cfg.m/100,
           'g_rev':o_cfg.g_rev,'mom':o_key[2],'entry':int(o_cfg.entry),'exit':o_cfg['exit'],'slots':int(o_cfg.slots)}
    d_sl = d_cfg.sl if pd.notna(d_cfg.sl) else None
    d_tr = d_cfg.trail if pd.notna(d_cfg.trail) else None

    r = tsim.run_regime(d_p, o_p, regime, stop_loss=d_sl, trailing_stop=d_tr)
    daily = r['_daily_rets']

    d_sl_s = f'{int(d_cfg.sl*100)}%' if pd.notna(d_cfg.sl) else 'X'
    o_sl_s = f'{int(o_cfg.sl*100)}%' if pd.notna(o_cfg.sl) else 'X'
    d_tr_s = f'{int(d_cfg.trail*100)}%' if pd.notna(d_cfg.trail) else 'X'
    o_tr_s = f'{int(o_cfg.trail*100)}%' if pd.notna(o_cfg.trail) else 'X'

    print(f'\n{"="*80}', flush=True)
    print(f'#{rank} {rule_type}_{cd}d', flush=True)
    print(f'  Cal={r["calmar"]:.2f}  CAGR={r["cagr"]:.1f}%  MDD={r["mdd"]:.1f}%  Sharpe={r["sharpe"]:.2f}  Sortino={r["sortino"]:.2f}  Alpha={r["alpha"]:.1f}%', flush=True)
    print(f'  전환: {switches}회 ({switches/years:.1f}회/년)  공격일: {boost_days}/{len(dates)} ({boost_days/len(dates)*100:.0f}%)', flush=True)
    print(f'  방어: {d_key[0]} g={d_key[1]} mom={d_key[2]}  E{int(d_cfg.entry)} X{d_cfg["exit"]} S{int(d_cfg.slots)}  sl={d_sl_s} trail={d_tr_s}', flush=True)
    print(f'  공격: {o_key[0]} g={o_key[1]} mom={o_key[2]}  E{int(o_cfg.entry)} X{o_cfg["exit"]} S{int(o_cfg.slots)}  sl={o_sl_s} trail={o_tr_s}', flush=True)

    year_periods = {'2021':('20210104','20211231'), '2022':('20220101','20221231'),
                    '2023':('20230101','20231231'), '2024':('20240101','20241231'),
                    '2025':('20250101','20251231'), '2026':('20260101','20260403')}

    print(f'\n  {"연도":>6} {"CAGR":>7} {"MDD":>6} {"벤치":>7} {"Alpha":>7}', flush=True)
    print(f'  {"-"*35}', flush=True)
    for yr, (start, end) in year_periods.items():
        pr = [daily[i] for i, d in enumerate(dates) if start <= d <= end]
        if not pr: continue
        cum = 1.0; pk = 1.0; mdd_v = 0.0
        for ret in pr:
            cum *= (1+ret); pk = max(pk, cum); mdd_v = min(mdd_v, (cum-pk)/pk)
        ann = (cum ** (252/max(len(pr),1)) - 1) * 100

        bp_slice = bp[(bp.index >= pd.Timestamp(start)) & (bp.index <= pd.Timestamp(end))]
        if len(bp_slice.dropna()) >= 2:
            bp_cum = bp_slice.dropna().iloc[-1] / bp_slice.dropna().iloc[0]
            bp_ann = (bp_cum ** (252/max(len(pr),1)) - 1) * 100
        else:
            bp_ann = 0
        alpha = ann - bp_ann
        print(f'  {yr:>6} {ann:+6.0f}% {mdd_v*100:5.0f}% {bp_ann:+6.0f}% {alpha:+6.0f}%', flush=True)

print('\n완료', flush=True)
