"""DART 공시 유형별 승률 EDA — 12가지 공시 후 주가 변화 측정"""
import sys, os, requests, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd, numpy as np
from pathlib import Path
from config import DART_API_KEY

PROJECT = Path(__file__).parent.parent
API_KEY = DART_API_KEY
from config import TELEGRAM_BOT_TOKEN as BOT, TELEGRAM_PRIVATE_ID as PID

ohlcv = pd.read_parquet(sorted(PROJECT.glob('data_cache/all_ohlcv_2017*.parquet'))[-1])
ohlcv.index = pd.to_datetime(ohlcv.index)
ohlcv = ohlcv.replace(0, np.nan)
print(f'OHLCV: {ohlcv.shape}', flush=True)

def collect_dart(keywords, years=range(2019, 2027)):
    results = []
    seen = set()
    for year in years:
        for ms in range(1, 13):  # 월별 검색 (2개월->1개월)
            s = f'{year}{ms:02d}01'
            if ms == 12:
                e = f'{year}1231'
            elif ms == 2:
                e = f'{year}0228'
            else:
                e = f'{year}{ms:02d}30'
            if year == 2026 and ms > 4:
                break
            for pg in range(1, 15):  # 5->14페이지
                resp = requests.get('https://opendart.fss.or.kr/api/list.json', params={
                    'crtfc_key': API_KEY, 'bgn_de': s, 'end_de': e,
                    'page_no': pg, 'page_count': 100,
                }, timeout=30)
                data = resp.json()
                if data.get('status') != '000':
                    break
                items = data.get('list', [])
                if not items:
                    break
                for item in items:
                    title = item.get('report_nm', '')
                    for kw in keywords:
                        if kw in title:
                            sc = item.get('stock_code', '')
                            rno = item.get('rcept_no', '')
                            dedup = f'{sc}_{rno}'
                            if len(sc) == 6 and dedup not in seen:
                                seen.add(dedup)
                                results.append({
                                    'stock_code': sc,
                                    'corp_name': item.get('corp_name'),
                                    'rcept_dt': item.get('rcept_dt'),
                                    'report_nm': title,
                                    'keyword': kw,
                                })
                            break
                time.sleep(0.12)
    return pd.DataFrame(results) if results else pd.DataFrame()

def measure_returns(df_in):
    pr = []
    for _, row in df_in.iterrows():
        tk = row['stock_code']
        dt = pd.Timestamp(row['rcept_dt'])
        if tk not in ohlcv.columns:
            continue
        prices = ohlcv[tk].dropna()
        future = prices[prices.index >= dt]
        if len(future) < 21:
            continue
        p0 = future.iloc[0]
        if p0 <= 0 or np.isnan(p0):
            continue
        r = {'ticker': tk, 'name': row['corp_name'], 'rcept_dt': row['rcept_dt']}
        for d in [1, 3, 5, 10, 20]:
            if len(future) > d:
                r[f'd{d}'] = (future.iloc[d] / p0 - 1) * 100
        pr.append(r)
    return pd.DataFrame(pr) if pr else pd.DataFrame()

# === 12 테스트 ===
tests = [
    ('1.자기주식취득', ['자기주식취득결정']),
    ('2.자기주식처분', ['자기주식처분결정']),
    ('3.유상증자', ['유상증자결정']),
    ('4.전환사채(CB)', ['전환사채권발행결정']),
    ('5.무상증자', ['무상증자결정']),
    ('6.합병결정', ['합병결정']),
    ('7.영업양수도', ['영업양수결정', '영업양도결정']),
    ('8.타법인주식취득', ['타법인주식및출자증권취득결정']),
    ('9.주식교환', ['주식교환', '주식이전']),
    ('10.신주인수권부사채', ['신주인수권부사채권발행결정']),
    ('11.교환사채', ['교환사채권발행결정']),
    ('12.감자결정', ['감자결정', '주식병합결정']),
]

all_results = []

for label, keywords in tests:
    print(f'{label} 수집...', end='', flush=True)
    df = collect_dart(keywords)
    if len(df) == 0:
        print(f' 0건')
        continue
    pdf = measure_returns(df)
    if len(pdf) < 5:
        print(f' {len(pdf)}건(부족)')
        continue
    d5 = pdf['d5'].mean()
    d20 = pdf['d20'].mean()
    wr = (pdf['d20'] > 0).mean() * 100
    med = pdf['d20'].median()
    print(f' {len(pdf)}건 D+20={d20:+.1f}% 승률={wr:.0f}%')
    all_results.append({'test': label, 'count': len(pdf), 'd5': d5, 'd20': d20, 'd20_wr': wr, 'd20_med': med})

# === 텔레그램 ===
print(f'\n총 {len(all_results)}가지 완료', flush=True)

sorted_r = sorted(all_results, key=lambda x: x['d20_wr'], reverse=True)

msg = '<b>[DART 공시 유형별 승률 EDA]</b>\n\n'
msg += '2019~2026 상장종목 대상\n'
msg += '공시 발표 후 D+20(20거래일) 기준\n\n'

for r in sorted_r:
    wr = r['d20_wr']
    emoji = '\U0001f7e2' if wr > 55 else ('\U0001f7e1' if wr > 45 else '\U0001f534')
    msg += f'{emoji} <b>{r["test"]}</b> ({r["count"]}건)\n'
    msg += f'    D+5: {r["d5"]:+.1f}%  D+20: {r["d20"]:+.1f}%\n'
    msg += f'    승률: {wr:.0f}%  중앙값: {r["d20_med"]:+.1f}%\n\n'

msg += '<b>해석:</b>\n'
msg += '\U0001f7e2 55%+ = 유의미한 시그널\n'
msg += '\U0001f7e1 45~55% = 동전 수준\n'
msg += '\U0001f534 45%- = 역시그널(회피용)\n\n'

good = [r for r in sorted_r if r['d20_wr'] > 55]
bad = [r for r in sorted_r if r['d20_wr'] < 45]
msg += '<b>결론:</b>\n'
if good:
    msg += '유의미: ' + ', '.join(r['test'] for r in good) + '\n'
else:
    msg += '유의미한 시그널 없음\n'
if bad:
    msg += '회피용: ' + ', '.join(r['test'] for r in bad)

if len(msg) > 4096:
    msg = msg[:4090] + '...'

resp = requests.post(f'https://api.telegram.org/bot{BOT}/sendMessage',
                     data={'chat_id': PID, 'text': msg, 'parse_mode': 'HTML'}, timeout=30)
print(f'\n텔레그램: {resp.status_code}')

pd.DataFrame(all_results).to_csv(str(PROJECT / 'backtest' / 'dart_disclosure_eda.csv'), index=False, encoding='utf-8-sig')
print('저장 완료')
