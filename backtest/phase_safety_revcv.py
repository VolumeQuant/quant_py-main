"""안전망 추가 BT: 매출 변동계수(CV) 임계값 차단
가설: 4분기 매출 CV(std/mean) > T → 매출 변동성 큰 종목 차단
링네트/아이티센글로벌 같은 매출 일회성 점프 캐치
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

# === PIT 매출 CV 사전계산 ===
# 종목별로 분기 매출 history → 각 rcept_dt에 trailing 4Q CV
print('매출 CV 사전계산 (PIT)...', flush=True)
t0 = time.time()

# 종목 → list of (rcept_dt, cv) events
cv_events = {}
fs_files = sorted(DATA.glob('fs_dart_*.parquet'))
print(f'  fs_dart 파일: {len(fs_files)}개', flush=True)

for i, fp in enumerate(fs_files):
    ticker = fp.stem.replace('fs_dart_', '')
    try:
        df = pd.read_parquet(fp)
        if '공시구분' not in df.columns or 'rcept_dt' not in df.columns:
            continue
        q = df[(df['공시구분']=='q') & (df['계정']=='매출액')].sort_values('기준일')
        if len(q) < 4:
            continue
        # 각 분기에서 trailing 4Q CV 계산
        events = []
        vals = q['값'].values
        dates_q = q['기준일'].values
        rcepts = q['rcept_dt'].values
        for j in range(3, len(vals)):  # 인덱스 3부터 (4분기 확보)
            window = vals[j-3:j+1]  # 최근 4개 (자신 포함)
            mean_v = np.mean(window)
            if mean_v <= 0: continue
            cv = np.std(window) / abs(mean_v)
            rcept = rcepts[j]
            if pd.notna(rcept):
                events.append((pd.Timestamp(rcept), cv))
        if events:
            cv_events[ticker] = events
    except Exception:
        pass
    if (i+1) % 500 == 0:
        print(f'  [{i+1}/{len(fs_files)}] {time.time()-t0:.0f}s', flush=True)

print(f'  완료: {len(cv_events)}종목, {time.time()-t0:.1f}s', flush=True)


def get_cv_at_date(ticker, date_ts):
    """date_ts 시점에서 가장 최근(이미 공시된) CV"""
    if ticker not in cv_events:
        return None
    events = cv_events[ticker]
    # rcept_dt <= date_ts 중 가장 최근
    valid = [(rd, cv) for rd, cv in events if rd <= date_ts]
    if not valid:
        return None
    return valid[-1][1]


def filter_by_cv(ranking_list, ts, threshold):
    new_list = []
    for r in ranking_list:
        cv = get_cv_at_date(r['ticker'], ts)
        if cv is not None and cv > threshold:
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
        regime_dict=regime,
        trailing_stop=-0.15, stop_loss=-0.10,
        g_sub1_o=GS[0], g_sub2_o=GS[1], g_sub3_o=GS[2],
        g_w1_o=GS[3], g_w2_o=GS[4], g_w3_o=GS[5],
        g_sub1_d=GS[0], g_sub2_d=GS[1], g_sub3_d=GS[2],
        g_w1_d=GS[3], g_w2_d=GS[4], g_w3_d=GS[5],
    )

results = []
r = run_bt({d: boost_rk[d] for d in pd_})
results.append({'label':'baseline','t':None,**{k:r[k] for k in ['cagr','mdd','calmar','sharpe','sortino','total']}})
print(f'\nbaseline: Cal={r["calmar"]:.3f}', flush=True)

print('\n=== 매출 CV 임계값별 BT ===', flush=True)
for T in [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0]:
    new_rk = {}
    for d in pd_:
        ts = pd.Timestamp(d)
        new_rk[d] = filter_by_cv(boost_rk[d], ts, T)
    r = run_bt(new_rk)
    results.append({'label':f'CV>{T}','t':T,**{k:r[k] for k in ['cagr','mdd','calmar','sharpe','sortino','total']}})
    print(f'  CV > {T}: Cal={r["calmar"]:.3f} CAGR={r["cagr"]:.1f}% MDD={r["mdd"]:.2f}% 누적={r["total"]:.0f}%', flush=True)

# 5/11 시점 검증
print('\n=== 5/11 표본 종목들 CV ===', flush=True)
ts_511 = pd.Timestamp('2026-05-11')
for tk, nm in [('042500','링네트'), ('124500','아이티센글로벌'), ('046940','우원개발'),
               ('088130','동아엘텍'), ('402340','SK스퀘어'), ('000660','SK하이닉스'),
               ('024840','KBI메탈'), ('006910','보성파워텍'), ('171090','선익시스템')]:
    cv = get_cv_at_date(tk, ts_511)
    print(f'  {nm}({tk}): CV = {cv:.3f}' if cv is not None else f'  {nm}: 데이터 없음')

df = pd.DataFrame(results).sort_values('calmar', ascending=False).reset_index(drop=True)
df.to_csv('C:/dev/backtest/phase_safety_revcv_result.csv', index=False, encoding='utf-8-sig')
print('\n=== Top 5 (Cal 정렬) ===')
print(df.head(5).to_string(index=False))
