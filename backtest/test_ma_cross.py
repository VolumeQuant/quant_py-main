"""MA 크로스 전략 백테스트 — v76 소스 무변경, 별도 테스트
골든크로스/데드크로스/정배열 등 다양한 MA 전략 테스트
"""
import sys, json, numpy as np, pandas as pd, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, 'c:/dev')
sys.path.insert(0, 'c:/dev/backtest')
from pathlib import Path
from turbo_simulator import TurboSimulator

# 데이터 로드
t0 = time.time()
ohlcv = pd.read_parquet('c:/dev/data_cache/all_ohlcv_20190603_20260406.parquet').replace(0, np.nan)
bench = pd.read_parquet('c:/dev/data_cache/kospi_yf.parquet')
bt = Path('c:/dev/backtest/bt_test_A')
dates = sorted([f.stem.replace('ranking_', '') for f in bt.glob('ranking_*.json')])
rk = {}
for d in dates:
    rk[d] = json.load(open(bt / f'ranking_{d}.json', 'r', encoding='utf-8')).get('rankings', [])

# 국면 규칙 (KP_MA200_5d)
kospi = pd.read_parquet('c:/dev/data_cache/kospi_yf.parquet').iloc[:, 0].dropna()
km200 = kospi.rolling(200).mean()
mode = False; streak = 0; ss = False; rd = {}
for d in dates:
    ts = pd.Timestamp(d)
    kv = kospi.get(ts, None); mv = km200.get(ts, None)
    s = (kv > mv) if kv is not None and mv is not None else mode
    if s == ss: streak += 1
    else: streak = 1; ss = s
    if streak >= 5 and mode != s: mode = s
    rd[d] = mode

# v76 가중치
op = {'v': 0.15, 'q': 0.05, 'g': 0.60, 'm': 0.20, 'g_rev': 0.6, 'entry': 5, 'exit': 8, 'slots': 3, 'mom': '12m-1m'}
dp = {'v': 0.15, 'q': 0.10, 'g': 0.25, 'm': 0.50, 'g_rev': 0.7, 'entry': 5, 'exit': 8, 'slots': 5, 'mom': '6m-1m'}

# 종목별 MA 사전계산
print('MA 사전계산...', flush=True)
ma_cache = {}
for ma_n in [5, 10, 20, 40, 60, 120]:
    ma_cache[ma_n] = ohlcv.rolling(ma_n).mean()
print(f'완료 ({time.time()-t0:.0f}s)', flush=True)

def get_ma(ticker, date_ts, ma_n):
    if ticker not in ohlcv.columns:
        return None
    val = ma_cache[ma_n].get(date_ts, pd.Series()).get(ticker)
    if pd.notna(val):
        return val
    return None

def get_price(ticker, date_ts):
    if ticker not in ohlcv.columns:
        return None
    val = ohlcv.get(date_ts, pd.Series()).get(ticker)
    if pd.notna(val):
        return val
    return None

def filter_by_condition(rk_data, dates, condition_fn):
    """condition_fn(ticker, date_ts) → True면 유지"""
    filtered = {}
    for d in dates:
        ts = pd.Timestamp(d)
        kept = [x for x in rk_data.get(d, []) if condition_fn(x['ticker'], ts)]
        filtered[d] = kept
    return filtered

def run_test(name, filtered):
    tsim = TurboSimulator(filtered, dates, ohlcv, bench=bench)
    r = tsim.run_regime(dp, op, rd, stop_loss=-0.10, trailing_stop=-0.15,
        g_sub1_d='rev_z', g_sub2_d='op_margin_z', g_sub1_o='oca_z', g_sub2_o='op_margin_z')
    avg = np.mean([len(v) for v in filtered.values()])
    print(f'{name:<35} {avg:>4.0f}종목  CAGR={r["cagr"]:>6.1f}%  MDD={r["mdd"]:>5.1f}%  Cal={r["calmar"]:>5.2f}  Sh={r["sharpe"]:>5.2f}', flush=True)
    return r

print(f'\n{"="*80}', flush=True)
print('MA 크로스 전략 백테스트', flush=True)
print(f'{"="*80}', flush=True)

# 현행
print('\n[기준]', flush=True)
run_test('현행 v76 (MA120만)', rk)

# A. 골든크로스 진입 (단기 > 장기일 때만 매수 허용)
print('\n[A. 골든크로스 진입 — 단기MA > 장기MA인 종목만]', flush=True)
for short, long in [(5, 20), (10, 40), (20, 60), (20, 120), (60, 120)]:
    def gc_cond(tk, ts, s=short, l=long):
        ms = get_ma(tk, ts, s)
        ml = get_ma(tk, ts, l)
        if ms is None or ml is None: return True
        return ms > ml
    filt = filter_by_condition(rk, dates, gc_cond)
    run_test(f'골든크로스 MA{short}>MA{long}', filt)

# B. 데드크로스 제거 (단기 < 장기인 종목 제거 = 매도 신호)
print('\n[B. 데드크로스 제거 — 단기MA < 장기MA이면 제거]', flush=True)
for short, long in [(5, 20), (10, 40), (20, 60), (20, 120), (60, 120)]:
    def dc_cond(tk, ts, s=short, l=long):
        ms = get_ma(tk, ts, s)
        ml = get_ma(tk, ts, l)
        if ms is None or ml is None: return True
        return ms >= ml  # 데드크로스(단기<장기)이면 제거
    filt = filter_by_condition(rk, dates, dc_cond)
    run_test(f'데드크로스제거 MA{short}<MA{long}', filt)

# C. 정배열 (MA20 > MA60 > MA120)
print('\n[C. 정배열 — 여러 MA가 순서대로 정렬]', flush=True)
for combo_name, ma_list in [('MA20>MA60>MA120', [20,60,120]), ('MA10>MA40>MA120', [10,40,120]), ('MA20>MA60', [20,60])]:
    def align_cond(tk, ts, ml=ma_list):
        vals = []
        for n in ml:
            v = get_ma(tk, ts, n)
            if v is None: return True
            vals.append(v)
        return all(vals[i] > vals[i+1] for i in range(len(vals)-1))
    filt = filter_by_condition(rk, dates, align_cond)
    run_test(f'정배열 {combo_name}', filt)

# D. 가격 > MAn (현재가가 MA 위)
print('\n[D. 현재가 > MAn]', flush=True)
for ma_n in [20, 60]:
    def price_above(tk, ts, n=ma_n):
        p = get_price(tk, ts)
        m = get_ma(tk, ts, n)
        if p is None or m is None: return True
        return p > m
    filt = filter_by_condition(rk, dates, price_above)
    run_test(f'현재가 > MA{ma_n}', filt)

# E. 골든크로스 + 현재가 MA20 위 (복합)
print('\n[E. 복합 전략]', flush=True)
def combo1(tk, ts):
    p = get_price(tk, ts)
    m20 = get_ma(tk, ts, 20)
    m60 = get_ma(tk, ts, 60)
    if p is None or m20 is None or m60 is None: return True
    return p > m20 and m20 > m60

filt = filter_by_condition(rk, dates, combo1)
run_test('가격>MA20 AND MA20>MA60', filt)

def combo2(tk, ts):
    p = get_price(tk, ts)
    m20 = get_ma(tk, ts, 20)
    m60 = get_ma(tk, ts, 60)
    m120 = get_ma(tk, ts, 120)
    if p is None or m20 is None or m60 is None or m120 is None: return True
    return p > m20 and m20 > m60 and m60 > m120

filt = filter_by_condition(rk, dates, combo2)
run_test('가격>MA20>MA60>MA120 (완전정배열)', filt)

# 52주 고점 대비 + MA20
def combo3(tk, ts):
    p = get_price(tk, ts)
    m20 = get_ma(tk, ts, 20)
    if p is None or m20 is None: return True
    if p < m20: return False  # MA20 아래면 제거
    # 52주 고점 대비 -20% 이내
    if tk in ohlcv.columns:
        prices = ohlcv[tk].dropna()
        if ts in prices.index:
            idx = prices.index.get_loc(ts)
            lb = min(252, idx)
            if lb > 0:
                hi = prices.iloc[idx-lb:idx+1].max()
                if hi > 0 and (p/hi - 1) < -0.20:
                    return False
    return True

filt = filter_by_condition(rk, dates, combo3)
run_test('MA20위 + 고점대비-20%이내', filt)

print(f'\n총 소요: {time.time()-t0:.0f}s', flush=True)
