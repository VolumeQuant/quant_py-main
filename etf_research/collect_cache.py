"""ETF 종합 데이터 캐시 수집 (회사/집 PC, krx_auth.login). 1회 수집 → 오프라인 분석 재사용.
순차+1초. 단계별 체크포인트(재실행 시 이미 받은 건 skip). 백그라운드 실행 권장.
실행: python etf_research/collect_cache.py
"""
import sys, time, json
from pathlib import Path
import pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import krx_auth
if not krx_auth.login():
    print('[중단] 로그인 실패'); sys.exit(1)
import pykrx.stock as s

C = Path(__file__).parent / '_cache'; C.mkdir(exist_ok=True)
SLEEP = 1.0
LEV = ['레버리지','인버스','2X','2x','곱버스']
MM = ['머니마켓','단기채','단기통안','채권','금리','CD금리','SOFR','국공채','종합채','크레딧','회사채','MMF','초단기','단기자금','만기매칭']
SNAP_DATES = ['20260115','20260216','20260316','20260416','20260515','20260529']  # 월별 + 최신
OHLCV_FROM = '20250101'


def bd(d):
    r = s.get_nearest_business_day_in_a_week(d); time.sleep(SLEEP); return r

BASE = s.get_nearest_business_day_in_a_week()
print(f'BASE={BASE}', flush=True)

# === Stage 0: 전체 이름 ===
NF = C / 'names.json'
names = json.loads(NF.read_text(encoding='utf-8')) if NF.exists() else {}
tickers = s.get_etf_ticker_list(BASE); time.sleep(SLEEP)
print(f'[S0] 전체 ETF {len(tickers)}, 이름 캐시 {len(names)}', flush=True)
todo = [t for t in tickers if t not in names]
for i, t in enumerate(todo):
    try:
        v = s.get_etf_ticker_name(t)
        if hasattr(v, 'iloc'): v = v.iloc[0]
        names[t] = str(v)
    except Exception: names[t] = t
    time.sleep(SLEEP)
    if i % 50 == 0:
        NF.write_text(json.dumps(names, ensure_ascii=False), encoding='utf-8')
        print(f'  names {i}/{len(todo)}', flush=True)
NF.write_text(json.dumps(names, ensure_ascii=False), encoding='utf-8')
print(f'[S0] done {len(names)}', flush=True)

# === Stage 1: 분류 ===
def is_lev(t): return any(k in names.get(t,'') for k in LEV)
def is_mm(t): return any(k in names.get(t,'') for k in MM)
def is_active(t): return '액티브' in names.get(t,'')
active_eq = [t for t in tickers if is_active(t) and not is_mm(t) and not is_lev(t)]
# 유동성 상위
chg = s.get_etf_price_change_by_ticker(bd((pd.Timestamp(BASE)-pd.Timedelta(days=7)).strftime('%Y%m%d')), BASE); time.sleep(SLEEP)
chg.index = chg.index.astype(str)
vcol = next(c for c in chg.columns if '거래대금' in c)
liquid = chg.sort_values(vcol, ascending=False).head(250).index.tolist()
uni = {'active_equity': active_eq, 'liquid': liquid, 'n_total': len(tickers)}
(C/'universe.json').write_text(json.dumps(uni, ensure_ascii=False, indent=1), encoding='utf-8')
print(f'[S1] active_equity {len(active_eq)}, liquid {len(liquid)}', flush=True)

# === Stage 2: 홀딩스 스냅샷 (active_equity × SNAP_DATES) ===
HF = C / 'holdings.parquet'
done = set()
if HF.exists():
    prev = pd.read_parquet(HF); done = set(zip(prev['snap'], prev['etf']))
    rows = prev.to_dict('records')
else:
    rows = []
snaps = [bd(d) for d in SNAP_DATES]
print(f'[S2] 스냅 {snaps} × active {len(active_eq)} = {len(snaps)*len(active_eq)} (done {len(done)})', flush=True)
cnt = 0
for sd in snaps:
    for t in active_eq:
        if (sd, t) in done: continue
        try:
            p = s.get_etf_portfolio_deposit_file(t, sd)
            if p is not None and len(p):
                p.index = p.index.astype(str); p = p[~p.index.duplicated()]
                ncol = next((c for c in p.columns if '종목명' in c), None)
                wcol = next((c for c in p.columns if '비중' in c), None)
                for stk in p.index:
                    if stk.startswith(('F0','CASH')) or not stk.isdigit(): continue
                    rows.append({'snap': sd, 'etf': t, 'stock': stk,
                                 'sname': str(p.loc[stk, ncol]) if ncol else '',
                                 'weight': float(p.loc[stk, wcol]) if wcol else 0.0})
        except Exception: pass
        time.sleep(SLEEP); cnt += 1
        if cnt % 100 == 0:
            pd.DataFrame(rows).to_parquet(HF)
            print(f'  holdings {cnt} (rows {len(rows)})', flush=True)
pd.DataFrame(rows).to_parquet(HF)
print(f'[S2] done rows {len(rows)}', flush=True)

# === Stage 3: 유동 universe OHLCV (NAV/종가/거래대금) ===
OF = C / 'ohlcv_liquid.parquet'
if not OF.exists():
    orows = []
    for i, t in enumerate(liquid):
        try:
            df = s.get_etf_ohlcv_by_date(OHLCV_FROM, BASE, t)
            if df is not None and len(df):
                vcol2 = next((c for c in df.columns if '거래대금' in c), None)
                for d, r in df.iterrows():
                    orows.append({'date': d.strftime('%Y%m%d'), 'etf': t,
                                  'nav': float(r['NAV']) if 'NAV' in r else 0.0,
                                  'close': float(r['종가']), 'value': float(r[vcol2]) if vcol2 else 0.0})
        except Exception: pass
        time.sleep(SLEEP)
        if i % 50 == 0: print(f'  ohlcv {i}/{len(liquid)}', flush=True)
    pd.DataFrame(orows).to_parquet(OF)
    print(f'[S3] done rows {len(orows)}', flush=True)
else:
    print('[S3] skip (exists)', flush=True)

# === Stage 4: 투자자 순매수 (유동 universe, BASE 당일) ===
IF = C / 'investor.parquet'
if not IF.exists():
    INST = ['금융투자','보험','투신','사모','은행','기타금융','연기금등','연기금']
    irows = []
    for i, t in enumerate(liquid):
        try:
            tv = s.get_etf_trading_volume_and_value(BASE, BASE, t)
            nb = tv[('거래대금','순매수')] if isinstance(tv.columns, pd.MultiIndex) else tv['순매수']
            irows.append({'etf': t,
                          'foreign': float(sum(nb.get(k,0) for k in ['외국인','기타외국인'])),
                          'inst': float(sum(nb.get(k,0) for k in INST))})
        except Exception: pass
        time.sleep(SLEEP)
        if i % 50 == 0: print(f'  investor {i}/{len(liquid)}', flush=True)
    pd.DataFrame(irows).to_parquet(IF)
    print(f'[S4] done rows {len(irows)}', flush=True)
else:
    print('[S4] skip (exists)', flush=True)

print('=== 수집 완료 ===', flush=True)
