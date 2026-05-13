"""안전망 BT: 직전 분기 매출 점프 차단
가설: 최근 분기 매출 / 직전 4분기 평균 > T 종목 차단
링네트 같은 매출 일회성 점프 (사업 변곡점 + QoQ 변동) 차단
"""
import sys, json, glob, time
from pathlib import Path
sys.path.insert(0, 'C:/dev/backtest')
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator

STATE = Path('C:/dev/state')
DATA = Path('C:/dev/data_cache')

def load_rk(d):
    data = {}
    for fp in sorted(d.glob('ranking_*.json')):
        k = fp.stem.replace('ranking_','')
        if len(k) != 8 or not k.isdigit(): continue
        if k not in data:
            data[k] = json.load(open(fp, 'r', encoding='utf-8'))
    return data


def calc_regime(target_dates, kospi, ma170, confirm=8):
    reg = {}; md = False; stk = 0; ss = None
    for d in target_dates:
        ts = pd.Timestamp(d); kv = kospi.get(ts); mv = ma170.get(ts)
        if kv is None or pd.isna(mv): reg[d]=md; continue
        s = kv > mv
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= confirm and md != s: md = s
        reg[d] = md
    return reg


print('로딩...', flush=True)
boost_rd = load_rk(STATE)
defense_rd = load_rk(STATE / 'defense')
dates = sorted(set(boost_rd) & set(defense_rd))
boost_rk = {d: boost_rd[d]['rankings'] for d in dates}
ohlcv = pd.read_parquet(sorted(glob.glob('C:/dev/data_cache/all_ohlcv_2017*.parquet'))[-1]).replace(0, np.nan)
kdf = pd.read_parquet('C:/dev/data_cache/kospi_yf.parquet')
kospi = kdf.iloc[:, 0].sort_index()
ma170 = kospi.rolling(170).mean()

pd_ = [d for d in dates if '20180702' <= d <= '20260511']
regime = calc_regime(pd_, kospi, ma170)

# PIT 매출 점프 사전계산
print('매출 점프 사전계산 (PIT)...', flush=True)
t0 = time.time()
jump_events = {}
fs_files = sorted(DATA.glob('fs_dart_*.parquet'))

for fp in fs_files:
    ticker = fp.stem.replace('fs_dart_', '')
    try:
        df = pd.read_parquet(fp)
        if '공시구분' not in df.columns or 'rcept_dt' not in df.columns:
            continue
        q = df[(df['공시구분']=='q') & (df['계정']=='매출액')].sort_values('기준일')
        if len(q) < 5:
            continue
        events = []
        vals = q['값'].values
        rcepts = q['rcept_dt'].values
        for j in range(4, len(vals)):  # 4분기 이상 history 후
            prev4 = vals[j-4:j]  # 직전 4분기
            cur = vals[j]
            prev_mean = np.mean(prev4)
            if prev_mean <= 0:
                continue
            jump = cur / prev_mean  # 비율 (1.0 = 같음, 5.0 = 5배)
            rcept = rcepts[j]
            if pd.notna(rcept):
                events.append((pd.Timestamp(rcept), jump))
        if events:
            jump_events[ticker] = events
    except Exception:
        pass

print(f'  완료: {len(jump_events)}종목, {time.time()-t0:.1f}s', flush=True)


def get_jump_at_date(ticker, date_ts):
    if ticker not in jump_events:
        return None
    valid = [(rd, j) for rd, j in jump_events[ticker] if rd <= date_ts]
    if not valid:
        return None
    return valid[-1][1]


def filter_by_jump(ranking_list, ts, threshold):
    new_list = []
    for r in ranking_list:
        jump = get_jump_at_date(r['ticker'], ts)
        if jump is not None and jump > threshold:
            continue
        new_list.append(r)
    new_list.sort(key=lambda x: x.get('weighted_rank', x['rank']))
    for i, r in enumerate(new_list, 1):
        r['rank'] = i; r['weighted_rank'] = float(i)
    return new_list


V80_O = {'v':0.15,'q':0.00,'g':0.55,'m':0.30,'g_rev':0.6,'entry':3,'exit':6,'slots':3,'mom':'12m'}
V80_D = {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,'entry':3,'exit':6,'slots':5,'mom':'6m-1m'}
GS = ('rev_z','oca_z',None,None,None,None)

def run_bt(new_rk_dict):
    tsim = TurboSimulator(new_rk_dict, pd_, ohlcv)
    return tsim.run_regime(
        defense_params=V80_D, offense_params=V80_O,
        regime_dict=regime, trailing_stop=-0.15, stop_loss=-0.10,
        g_sub1_o=GS[0], g_sub2_o=GS[1], g_sub3_o=GS[2],
        g_w1_o=GS[3], g_w2_o=GS[4], g_w3_o=GS[5],
        g_sub1_d=GS[0], g_sub2_d=GS[1], g_sub3_d=GS[2],
        g_w1_d=GS[3], g_w2_d=GS[4], g_w3_d=GS[5],
    )

results = []
r = run_bt({d: boost_rk[d] for d in pd_})
results.append({'label':'baseline','t':None,**{k:r[k] for k in ['cagr','mdd','calmar']}})
print(f'\nbaseline: Cal={r["calmar"]:.3f}', flush=True)

print('\n=== 매출 점프 임계값별 BT ===', flush=True)
for T in [1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 7.0, 10.0]:
    new_rk = {}
    for d in pd_:
        ts = pd.Timestamp(d)
        new_rk[d] = filter_by_jump(boost_rk[d], ts, T)
    r = run_bt(new_rk)
    results.append({'label':f'jump>{T}','t':T,**{k:r[k] for k in ['cagr','mdd','calmar']}})
    print(f'  jump > {T}: Cal={r["calmar"]:.3f} CAGR={r["cagr"]:.1f}% MDD={r["mdd"]:.2f}%', flush=True)

# 5/11 표본 검증
print('\n=== 5/11 종목별 매출 점프 ===', flush=True)
ts_511 = pd.Timestamp('2026-05-11')
for tk, nm in [('042500','링네트'), ('024840','KBI메탈'), ('124500','아이티센글로벌'),
               ('088130','동아엘텍'), ('171090','선익시스템'), ('006910','보성파워텍'),
               ('046940','우원개발'), ('402340','SK스퀘어'), ('000660','SK하이닉스')]:
    j = get_jump_at_date(tk, ts_511)
    print(f'  {nm}({tk}): jump = {j:.2f}배' if j is not None else f'  {nm}: 데이터 없음')

df = pd.DataFrame(results).sort_values('calmar', ascending=False).reset_index(drop=True)
df.to_csv('C:/dev/backtest/phase_safety_jump_result.csv', index=False, encoding='utf-8-sig')
print('\n=== Top 5 (Cal 정렬) ===')
print(df.head(5).to_string(index=False))
