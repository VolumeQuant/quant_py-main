"""외국인/기관 순매수(거래대금) 일별 by-ticker 수집 — 정식 BT용 (표본 EDA가 +5.4%p로 통과).
2022~2026 (2022 약세장 포함 = 단일상승국면 한계 해소). pykrx 1초 sleep 순차 (CLAUDE.md).
증분·재개형: 기존 parquet 로드 → 안 모은 날짜만 수집 → 50일마다 저장. 중단돼도 무손실.
실행: python research/collect_kr_investor_flows.py
산출: data_cache/kr_investor_flows.parquet (date, ticker, foreign_net억, inst_net억)
"""
import sys, time
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, r'C:\dev\claude-code\quant_py-main')
sys.stdout.reconfigure(encoding='utf-8')
import krx_auth
from pykrx import stock
ROOT = Path(r'C:\dev\claude-code\quant_py-main'); DATA = ROOT/'data_cache'
OUT = DATA/'kr_investor_flows.parquet'

print('pykrx 로그인:', krx_auth.login(), flush=True)

# BT 거래일 = ohlcv 인덱스 (2022~2026)
ohlcv = pd.read_parquet(sorted(DATA.glob('all_ohlcv_2017*.parquet'))[-1])
all_dates = [d.strftime('%Y%m%d') for d in ohlcv.index if '20220101' <= d.strftime('%Y%m%d') <= '20260609']

# 재개: 기존 수집분 로드
done = set()
existing = []
if OUT.exists():
    prev = pd.read_parquet(OUT); existing.append(prev); done = set(prev['date'].unique())
    print(f'기존 {len(done)}일 로드 → 건너뜀', flush=True)
todo = [d for d in all_dates if d not in done]
print(f'수집 대상 {len(todo)}일 ({todo[0] if todo else "-"}~{todo[-1] if todo else "-"}), 예상 {len(todo)*4}콜', flush=True)

rows = []
def flush():
    if not rows: return
    df = pd.DataFrame(rows)
    if existing: df = pd.concat([existing[0], df], ignore_index=True)
    df = df.drop_duplicates(['date','ticker'], keep='last')
    df.to_parquet(OUT)
    print(f'  💾 저장: 누적 {df["date"].nunique()}일 / {len(df)}행', flush=True)

for i, d in enumerate(todo):
    rec = {}  # ticker -> [foreign, inst]
    for inv, key in [('외국인','foreign'), ('기관합계','inst')]:
        for mkt in ['KOSPI','KOSDAQ']:
            try:
                time.sleep(1)
                df = stock.get_market_net_purchases_of_equities_by_ticker(d, d, mkt, inv)
                col = next((c for c in df.columns if '순매수거래대금' in str(c)), None)
                if col is not None:
                    for tk, v in (df[col]/1e8).items():
                        tk = str(tk).zfill(6)
                        rec.setdefault(tk, {})[key] = float(v)
            except Exception as e:
                print(f'  WARN {d} {mkt} {inv}: {str(e)[:50]}', flush=True)
    for tk, vals in rec.items():
        rows.append({'date': d, 'ticker': tk,
                     'foreign_net': vals.get('foreign', np.nan),
                     'inst_net': vals.get('inst', np.nan)})
    if (i+1) % 25 == 0:
        print(f'  진행 {i+1}/{len(todo)} ({d})', flush=True)
    if (i+1) % 50 == 0:
        flush(); existing[:] = [pd.read_parquet(OUT)]; rows.clear()

flush()
print('수집 완료', flush=True)
