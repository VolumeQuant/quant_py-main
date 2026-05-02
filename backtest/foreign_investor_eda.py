"""외국인 순매수 EDA — 외국인이 집중 매수하는 종목의 향후 주가 예측력 측정
pykrx로 외국인 순매수 데이터 수집 + OHLCV 매칭
"""
import sys, os, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd, numpy as np
import requests
from pathlib import Path

PROJECT = Path(__file__).parent.parent
from config import TELEGRAM_BOT_TOKEN as BOT, TELEGRAM_PRIVATE_ID as PID
def send_tg(msg):
    if len(msg) > 4096: msg = msg[:4090] + '...'
    requests.post(f'https://api.telegram.org/bot{BOT}/sendMessage',
                  data={'chat_id': PID, 'text': msg, 'parse_mode': 'HTML'}, timeout=30)

print('OHLCV 로드...', flush=True)
ohlcv = pd.read_parquet(sorted(PROJECT.glob('data_cache/all_ohlcv_2017*.parquet'))[-1])
ohlcv.index = pd.to_datetime(ohlcv.index)
ohlcv = ohlcv.replace(0, np.nan)

# pykrx로 외국인 순매수 수집 (표본 날짜)
from pykrx import stock as pykrx

# 월 1회 표본 (2019~2025, 약 80일)
sample_dates = []
for y in range(2019, 2026):
    for m in [1, 3, 5, 7, 9, 11]:
        # 해당 월의 첫 거래일 찾기
        d_str = f'{y}{m:02d}15'
        sample_dates.append(d_str)

print(f'표본 날짜: {len(sample_dates)}개', flush=True)

results = []
for i, d_str in enumerate(sample_dates):
    try:
        # 해당 날짜의 외국인 순매수 상위/하위
        df = pykrx.get_market_net_purchases_of_equities(d_str, d_str, 'KOSPI', '외국인')
        time.sleep(1)  # pykrx 1초 sleep

        if df is None or len(df) == 0:
            print(f'  {d_str}: 데이터 없음', flush=True)
            continue

        # 순매수금액 기준 정렬
        if '순매수거래량' not in df.columns and '순매수' not in str(df.columns):
            print(f'  {d_str}: 컬럼 불일치 {df.columns.tolist()[:5]}', flush=True)
            continue

        # 컬럼명 확인
        buy_col = None
        for c in df.columns:
            if '순매수' in str(c) and '금액' in str(c):
                buy_col = c
                break
        if buy_col is None:
            for c in df.columns:
                if '순매수' in str(c):
                    buy_col = c
                    break

        if buy_col is None:
            print(f'  {d_str}: 순매수 컬럼 못 찾음 {df.columns.tolist()[:5]}', flush=True)
            continue

        df = df.sort_values(buy_col, ascending=False)

        # 상위 10종목 (외국인 집중 매수)
        top10 = df.head(10).index.tolist()
        # 하위 10종목 (외국인 집중 매도)
        bot10 = df.tail(10).index.tolist()

        dt = pd.Timestamp(d_str)
        future_dates = ohlcv.index[ohlcv.index >= dt]
        if len(future_dates) < 21:
            continue

        for tk in top10:
            if tk not in ohlcv.columns:
                continue
            p0 = ohlcv.loc[future_dates[0], tk] if future_dates[0] in ohlcv.index else None
            if p0 is None or pd.isna(p0) or p0 <= 0:
                continue
            ret = {}
            for dd in [5, 10, 20]:
                if len(future_dates) > dd:
                    p = ohlcv.loc[future_dates[dd], tk]
                    if not pd.isna(p) and p > 0:
                        ret[f'd{dd}'] = (p / p0 - 1) * 100
            if ret:
                ret['group'] = 'foreign_buy_top10'
                ret['date'] = d_str
                results.append(ret)

        for tk in bot10:
            if tk not in ohlcv.columns:
                continue
            p0 = ohlcv.loc[future_dates[0], tk] if future_dates[0] in ohlcv.index else None
            if p0 is None or pd.isna(p0) or p0 <= 0:
                continue
            ret = {}
            for dd in [5, 10, 20]:
                if len(future_dates) > dd:
                    p = ohlcv.loc[future_dates[dd], tk]
                    if not pd.isna(p) and p > 0:
                        ret[f'd{dd}'] = (p / p0 - 1) * 100
            if ret:
                ret['group'] = 'foreign_sell_top10'
                ret['date'] = d_str
                results.append(ret)

        print(f'  [{i+1}/{len(sample_dates)}] {d_str}: top10={len(top10)}, bot10={len(bot10)}, 누적={len(results)}건', flush=True)

    except Exception as e:
        print(f'  {d_str}: 에러 {e}', flush=True)
        time.sleep(1)
        continue

if not results:
    print('결과 없음')
    send_tg('<b>[외국인 순매수 EDA]</b>\n\npykrx 수집 실패 - 데이터 없음')
    sys.exit(0)

rdf = pd.DataFrame(results)
print(f'\n총 {len(rdf)}건')

# 분석
print(f'\n{"="*60}')
print('외국인 순매수 EDA 결과')
print('='*60)
for grp in ['foreign_buy_top10', 'foreign_sell_top10']:
    sub = rdf[rdf['group'] == grp]
    if len(sub) < 10:
        continue
    d5 = sub['d5'].mean() if 'd5' in sub else 0
    d20 = sub['d20'].mean() if 'd20' in sub else 0
    d20_wr = (sub['d20'] > 0).mean() * 100 if 'd20' in sub else 0
    d20_med = sub['d20'].median() if 'd20' in sub else 0
    print(f'{grp}: {len(sub)}건 D+5={d5:+.1f}% D+20={d20:+.1f}% 승률={d20_wr:.0f}% 중앙={d20_med:+.1f}%')

# 텔레그램
buy = rdf[rdf['group'] == 'foreign_buy_top10']
sell = rdf[rdf['group'] == 'foreign_sell_top10']

msg = '<b>[외국인 순매수 EDA 결과]</b>\n\n'
msg += f'2019~2025 격월 표본 ({len(sample_dates)}일)\n'
msg += f'총 {len(rdf)}건 분석\n\n'

if len(buy) > 0:
    d20_wr = (buy['d20'] > 0).mean() * 100
    msg += f'<b>외국인 순매수 Top 10:</b>\n'
    msg += f'  {len(buy)}건\n'
    msg += f'  D+5: {buy["d5"].mean():+.1f}%\n'
    msg += f'  D+20: {buy["d20"].mean():+.1f}% (승률 {d20_wr:.0f}%)\n'
    msg += f'  D+20 중앙값: {buy["d20"].median():+.1f}%\n\n'

if len(sell) > 0:
    d20_wr_s = (sell['d20'] > 0).mean() * 100
    msg += f'<b>외국인 순매도 Top 10:</b>\n'
    msg += f'  {len(sell)}건\n'
    msg += f'  D+5: {sell["d5"].mean():+.1f}%\n'
    msg += f'  D+20: {sell["d20"].mean():+.1f}% (승률 {d20_wr_s:.0f}%)\n'
    msg += f'  D+20 중앙값: {sell["d20"].median():+.1f}%\n\n'

if len(buy) > 0 and len(sell) > 0:
    buy_wr = (buy['d20'] > 0).mean() * 100
    sell_wr = (sell['d20'] > 0).mean() * 100
    spread = buy['d20'].mean() - sell['d20'].mean()
    msg += f'<b>결론:</b>\n'
    msg += f'매수-매도 스프레드: {spread:+.1f}%\n'
    if buy_wr > 55:
        msg += f'외국인 매수 종목 승률 {buy_wr:.0f}% -> 유의미한 시그널!'
    elif buy_wr > 50:
        msg += f'외국인 매수 종목 승률 {buy_wr:.0f}% -> 약한 시그널'
    else:
        msg += f'외국인 매수 종목 승률 {buy_wr:.0f}% -> 시그널 없음'

send_tg(msg)
print('\ntelegram sent')
