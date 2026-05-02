"""실시간 시그널 EDA — 외국인 순매수, 거래량 급증, 공매도 등
pykrx/OHLCV 기반으로 당일~T+1 시그널의 주가 예측력 측정
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
    if len(msg) > 4096:
        msg = msg[:4090] + '...'
    requests.post(f'https://api.telegram.org/bot{BOT}/sendMessage',
                  data={'chat_id': PID, 'text': msg, 'parse_mode': 'HTML'}, timeout=30)

print('OHLCV 로드...', flush=True)
ohlcv = pd.read_parquet(sorted(PROJECT.glob('data_cache/all_ohlcv_2017*.parquet'))[-1])
ohlcv.index = pd.to_datetime(ohlcv.index)
ohlcv = ohlcv.replace(0, np.nan)

# 우리 유니버스 종목 (시총 1000억+ 상장종목)
# state ranking에서 최근 날짜의 종목 목록 사용
import json
ranking_files = sorted(PROJECT.glob('state/ranking_*.json'))
if ranking_files:
    with open(ranking_files[-1], 'r', encoding='utf-8') as f:
        latest_rk = json.load(f)
    universe = [item['ticker'] for item in latest_rk['rankings']]
    print(f'유니버스: {len(universe)}종목 (최근 ranking)')
else:
    universe = [c for c in ohlcv.columns if len(c) == 6]

# 분석 기간
dates = ohlcv.index[(ohlcv.index >= '2019-01-01') & (ohlcv.index <= '2026-04-18')]
print(f'분석 기간: {dates[0].date()} ~ {dates[-1].date()} ({len(dates)}일)')

all_results = []

# ══════════════════════════════════════════
# Test 1: 거래량 급증 (20일 평균 대비 3배+)
# ══════════════════════════════════════════
print('\n[1] 거래량 급증 분석...', flush=True)

# 거래량 데이터가 OHLCV에 있는지 확인 — 없으면 pykrx로
# OHLCV는 종가만 있을 수 있음. 확인
vol_data = None
vol_files = sorted(PROJECT.glob('data_cache/all_volume*.parquet'))
if vol_files:
    vol_data = pd.read_parquet(vol_files[-1])
    vol_data.index = pd.to_datetime(vol_data.index)
    print(f'  거래량 파일: {vol_files[-1].name}')

if vol_data is None:
    # pykrx로 거래량 수집은 시간이 너무 걸림
    # 대신 거래대금 데이터 확인
    val_files = sorted(PROJECT.glob('data_cache/all_trading_value*.parquet'))
    if val_files:
        vol_data = pd.read_parquet(val_files[-1])
        vol_data.index = pd.to_datetime(vol_data.index)
        print(f'  거래대금 파일: {val_files[-1].name}')

if vol_data is not None:
    events = []
    for tk in universe:
        if tk not in vol_data.columns or tk not in ohlcv.columns:
            continue
        vol = vol_data[tk].dropna()
        px = ohlcv[tk].dropna()
        ma20 = vol.rolling(20).mean()

        for dt in vol.index:
            if dt < pd.Timestamp('2019-01-01'):
                continue
            v = vol.get(dt)
            m = ma20.get(dt)
            if v is None or m is None or np.isnan(v) or np.isnan(m) or m <= 0:
                continue
            ratio = v / m
            if ratio >= 3.0:  # 20일 평균 대비 3배
                future = px[px.index > dt]
                if len(future) < 20:
                    continue
                p0 = px.get(dt)
                if p0 is None or p0 <= 0 or np.isnan(p0):
                    continue
                d5 = (future.iloc[4] / p0 - 1) * 100 if len(future) > 4 else None
                d20 = (future.iloc[19] / p0 - 1) * 100 if len(future) > 19 else None
                events.append({'ticker': tk, 'date': dt, 'ratio': ratio, 'd5': d5, 'd20': d20})

    if events:
        edf = pd.DataFrame(events)
        # 표본 제한 (너무 많으면 랜덤 샘플)
        if len(edf) > 5000:
            edf = edf.sample(5000, random_state=42)
        d20_wr = (edf['d20'] > 0).mean() * 100
        d20_avg = edf['d20'].mean()
        d20_med = edf['d20'].median()
        print(f'  거래량 3배+ 급증: {len(edf)}건 D+20={d20_avg:+.1f}% 승률={d20_wr:.0f}% 중앙={d20_med:+.1f}%')
        all_results.append({'test': '1.거래량3배급증', 'count': len(edf), 'd5': edf['d5'].mean(),
                           'd20': d20_avg, 'd20_wr': d20_wr, 'd20_med': d20_med})

        # 5배 급증
        edf5 = edf[edf['ratio'] >= 5.0]
        if len(edf5) >= 20:
            wr5 = (edf5['d20'] > 0).mean() * 100
            print(f'  거래량 5배+ 급증: {len(edf5)}건 D+20={edf5["d20"].mean():+.1f}% 승률={wr5:.0f}%')
            all_results.append({'test': '2.거래량5배급증', 'count': len(edf5), 'd5': edf5['d5'].mean(),
                               'd20': edf5['d20'].mean(), 'd20_wr': wr5, 'd20_med': edf5['d20'].median()})
else:
    print('  거래량/거래대금 데이터 없음 — 스킵')

# ══════════════════════════════════════════
# Test 2: 단기 모멘텀 (5일 수익률 상위/하위)
# ══════════════════════════════════════════
print('\n[2] 단기 모멘텀 분석...', flush=True)

events_up = []
events_down = []
sample_dates = dates[::5]  # 5일 간격 샘플링 (속도)

for dt in sample_dates:
    if dt < pd.Timestamp('2019-01-20'):
        continue
    dt_idx = ohlcv.index.get_loc(dt)
    if dt_idx < 5:
        continue

    rets_5d = {}
    for tk in universe:
        if tk not in ohlcv.columns:
            continue
        p_now = ohlcv[tk].iloc[dt_idx]
        p_5ago = ohlcv[tk].iloc[dt_idx - 5]
        if pd.isna(p_now) or pd.isna(p_5ago) or p_5ago <= 0:
            continue
        rets_5d[tk] = (p_now / p_5ago - 1) * 100

    if len(rets_5d) < 20:
        continue

    sorted_tks = sorted(rets_5d.keys(), key=lambda x: rets_5d[x], reverse=True)
    top10 = sorted_tks[:10]
    bottom10 = sorted_tks[-10:]

    future = ohlcv.index[ohlcv.index > dt]
    if len(future) < 20:
        continue

    for tk in top10:
        p0 = ohlcv[tk].iloc[dt_idx]
        if pd.isna(p0) or p0 <= 0:
            continue
        p20 = ohlcv.loc[future[19], tk] if len(future) > 19 else None
        p5 = ohlcv.loc[future[4], tk] if len(future) > 4 else None
        if p20 is not None and not np.isnan(p20):
            events_up.append({'d5': (p5/p0-1)*100 if p5 and not np.isnan(p5) else None,
                             'd20': (p20/p0-1)*100, 'ret5d': rets_5d[tk]})

    for tk in bottom10:
        p0 = ohlcv[tk].iloc[dt_idx]
        if pd.isna(p0) or p0 <= 0:
            continue
        p20 = ohlcv.loc[future[19], tk] if len(future) > 19 else None
        p5 = ohlcv.loc[future[4], tk] if len(future) > 4 else None
        if p20 is not None and not np.isnan(p20):
            events_down.append({'d5': (p5/p0-1)*100 if p5 and not np.isnan(p5) else None,
                               'd20': (p20/p0-1)*100, 'ret5d': rets_5d[tk]})

if events_up:
    udf = pd.DataFrame(events_up)
    ddf = pd.DataFrame(events_down)
    u_wr = (udf['d20'] > 0).mean() * 100
    d_wr = (ddf['d20'] > 0).mean() * 100
    print(f'  5일 상위10 (모멘텀): {len(udf)}건 D+20={udf["d20"].mean():+.1f}% 승률={u_wr:.0f}%')
    print(f'  5일 하위10 (역행): {len(ddf)}건 D+20={ddf["d20"].mean():+.1f}% 승률={d_wr:.0f}%')
    all_results.append({'test': '3.5일모멘텀상위', 'count': len(udf), 'd5': udf['d5'].mean(),
                       'd20': udf['d20'].mean(), 'd20_wr': u_wr, 'd20_med': udf['d20'].median()})
    all_results.append({'test': '4.5일모멘텀하위', 'count': len(ddf), 'd5': ddf['d5'].mean(),
                       'd20': ddf['d20'].mean(), 'd20_wr': d_wr, 'd20_med': ddf['d20'].median()})

# ══════════════════════════════════════════
# Test 3: 신고가/신저가 (52주)
# ══════════════════════════════════════════
print('\n[3] 52주 신고가/신저가 분석...', flush=True)

events_high = []
events_low = []

for dt in sample_dates:
    dt_idx = ohlcv.index.get_loc(dt)
    if dt_idx < 252:
        continue

    future = ohlcv.index[ohlcv.index > dt]
    if len(future) < 20:
        continue

    for tk in universe[:100]:  # 상위 100종목만 (속도)
        if tk not in ohlcv.columns:
            continue
        prices_252 = ohlcv[tk].iloc[dt_idx-252:dt_idx+1].dropna()
        if len(prices_252) < 200:
            continue
        p_now = prices_252.iloc[-1]
        if pd.isna(p_now) or p_now <= 0:
            continue

        high_52 = prices_252.max()
        low_52 = prices_252.min()

        p20 = ohlcv.loc[future[19], tk] if len(future) > 19 else None
        p5 = ohlcv.loc[future[4], tk] if len(future) > 4 else None

        if p_now >= high_52 * 0.98:  # 52주 최고 근처
            if p20 is not None and not np.isnan(p20):
                events_high.append({'d5': (p5/p_now-1)*100 if p5 and not np.isnan(p5) else None,
                                   'd20': (p20/p_now-1)*100})
        elif p_now <= low_52 * 1.02:  # 52주 최저 근처
            if p20 is not None and not np.isnan(p20):
                events_low.append({'d5': (p5/p_now-1)*100 if p5 and not np.isnan(p5) else None,
                                  'd20': (p20/p_now-1)*100})

if events_high:
    hdf = pd.DataFrame(events_high)
    ldf = pd.DataFrame(events_low) if events_low else pd.DataFrame()
    h_wr = (hdf['d20'] > 0).mean() * 100
    print(f'  52주 신고가: {len(hdf)}건 D+20={hdf["d20"].mean():+.1f}% 승률={h_wr:.0f}%')
    all_results.append({'test': '5.52주신고가', 'count': len(hdf), 'd5': hdf['d5'].mean(),
                       'd20': hdf['d20'].mean(), 'd20_wr': h_wr, 'd20_med': hdf['d20'].median()})
    if len(ldf) >= 20:
        l_wr = (ldf['d20'] > 0).mean() * 100
        print(f'  52주 신저가: {len(ldf)}건 D+20={ldf["d20"].mean():+.1f}% 승률={l_wr:.0f}%')
        all_results.append({'test': '6.52주신저가', 'count': len(ldf), 'd5': ldf['d5'].mean(),
                           'd20': ldf['d20'].mean(), 'd20_wr': l_wr, 'd20_med': ldf['d20'].median()})

# ══════════════════════════════════════════
# Test 4: RSI 과매수/과매도
# ══════════════════════════════════════════
print('\n[4] RSI 분석...', flush=True)

events_ob = []  # overbought
events_os = []  # oversold

for tk in universe[:100]:
    if tk not in ohlcv.columns:
        continue
    px = ohlcv[tk].dropna()
    if len(px) < 100:
        continue

    delta = px.diff()
    gain = delta.clip(lower=0)
    loss = (-delta.clip(upper=0))
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    for dt in sample_dates:
        if dt not in rsi.index:
            continue
        r = rsi.get(dt)
        if pd.isna(r):
            continue

        future = px[px.index > dt]
        if len(future) < 20:
            continue
        p0 = px.get(dt)
        if pd.isna(p0) or p0 <= 0:
            continue
        p20 = future.iloc[19] if len(future) > 19 else None
        p5 = future.iloc[4] if len(future) > 4 else None

        if r >= 70:  # 과매수
            if p20 and not np.isnan(p20):
                events_ob.append({'d5': (p5/p0-1)*100 if p5 and not np.isnan(p5) else None,
                                 'd20': (p20/p0-1)*100, 'rsi': r})
        elif r <= 30:  # 과매도
            if p20 and not np.isnan(p20):
                events_os.append({'d5': (p5/p0-1)*100 if p5 and not np.isnan(p5) else None,
                                 'd20': (p20/p0-1)*100, 'rsi': r})

if events_ob:
    obdf = pd.DataFrame(events_ob)
    osdf = pd.DataFrame(events_os) if events_os else pd.DataFrame()
    ob_wr = (obdf['d20'] > 0).mean() * 100
    print(f'  RSI>=70 과매수: {len(obdf)}건 D+20={obdf["d20"].mean():+.1f}% 승률={ob_wr:.0f}%')
    all_results.append({'test': '7.RSI과매수(70+)', 'count': len(obdf), 'd5': obdf['d5'].mean(),
                       'd20': obdf['d20'].mean(), 'd20_wr': ob_wr, 'd20_med': obdf['d20'].median()})
    if len(osdf) >= 20:
        os_wr = (osdf['d20'] > 0).mean() * 100
        print(f'  RSI<=30 과매도: {len(osdf)}건 D+20={osdf["d20"].mean():+.1f}% 승률={os_wr:.0f}%')
        all_results.append({'test': '8.RSI과매도(30-)', 'count': len(osdf), 'd5': osdf['d5'].mean(),
                           'd20': osdf['d20'].mean(), 'd20_wr': os_wr, 'd20_med': osdf['d20'].median()})

# ══════════════════════════════════════════
# Test 5: 이동평균 돌파 (20일선 골든크로스)
# ══════════════════════════════════════════
print('\n[5] 이동평균 돌파 분석...', flush=True)

events_gc = []  # golden cross
events_dc = []  # death cross

for tk in universe[:100]:
    if tk not in ohlcv.columns:
        continue
    px = ohlcv[tk].dropna()
    ma5 = px.rolling(5).mean()
    ma20 = px.rolling(20).mean()

    prev_above = None
    for dt in px.index:
        if dt < pd.Timestamp('2019-01-01'):
            continue
        m5 = ma5.get(dt)
        m20 = ma20.get(dt)
        if pd.isna(m5) or pd.isna(m20):
            continue
        above = m5 > m20

        if prev_above is not None and above and not prev_above:  # 골든크로스
            future = px[px.index > dt]
            if len(future) >= 20:
                p0 = px.get(dt)
                p5 = future.iloc[4] if len(future) > 4 else None
                p20 = future.iloc[19]
                if p0 > 0 and not np.isnan(p20):
                    events_gc.append({'d5': (p5/p0-1)*100 if p5 and not np.isnan(p5) else None,
                                     'd20': (p20/p0-1)*100})
        elif prev_above is not None and not above and prev_above:  # 데드크로스
            future = px[px.index > dt]
            if len(future) >= 20:
                p0 = px.get(dt)
                p5 = future.iloc[4] if len(future) > 4 else None
                p20 = future.iloc[19]
                if p0 > 0 and not np.isnan(p20):
                    events_dc.append({'d5': (p5/p0-1)*100 if p5 and not np.isnan(p5) else None,
                                     'd20': (p20/p0-1)*100})
        prev_above = above

if events_gc:
    gcdf = pd.DataFrame(events_gc)
    dcdf = pd.DataFrame(events_dc) if events_dc else pd.DataFrame()
    gc_wr = (gcdf['d20'] > 0).mean() * 100
    print(f'  골든크로스(5>20): {len(gcdf)}건 D+20={gcdf["d20"].mean():+.1f}% 승률={gc_wr:.0f}%')
    all_results.append({'test': '9.골든크로스5x20', 'count': len(gcdf), 'd5': gcdf['d5'].mean(),
                       'd20': gcdf['d20'].mean(), 'd20_wr': gc_wr, 'd20_med': gcdf['d20'].median()})
    if len(dcdf) >= 20:
        dc_wr = (dcdf['d20'] > 0).mean() * 100
        print(f'  데드크로스(5<20): {len(dcdf)}건 D+20={dcdf["d20"].mean():+.1f}% 승률={dc_wr:.0f}%')
        all_results.append({'test': '10.데드크로스5x20', 'count': len(dcdf), 'd5': dcdf['d5'].mean(),
                           'd20': dcdf['d20'].mean(), 'd20_wr': dc_wr, 'd20_med': dcdf['d20'].median()})

# ══════════════════════════════════════════
# 종합 + 텔레그램
# ══════════════════════════════════════════
print(f'\n총 {len(all_results)}가지 테스트 완료', flush=True)

sorted_r = sorted(all_results, key=lambda x: x['d20_wr'], reverse=True)

msg = '<b>[실시간 시그널 EDA 결과]</b>\n\n'
msg += '우리 유니버스 종목 대상 (2019~2026)\n'
msg += 'D+20(20거래일) 승률 기준\n\n'

for r in sorted_r:
    wr = r['d20_wr']
    emoji = '\U0001f7e2' if wr > 55 else ('\U0001f7e1' if wr > 45 else '\U0001f534')
    msg += f'{emoji} <b>{r["test"]}</b> ({r["count"]}건)\n'
    msg += f'    D+5: {r["d5"]:+.1f}%  D+20: {r["d20"]:+.1f}%\n'
    msg += f'    승률: {wr:.0f}%  중앙값: {r["d20_med"]:+.1f}%\n\n'

msg += '<b>해석:</b>\n'
msg += '\U0001f7e2 55%+ = 유의미\n'
msg += '\U0001f7e1 45~55% = 동전\n'
msg += '\U0001f534 45%- = 역시그널\n\n'

good = [r for r in sorted_r if r['d20_wr'] > 55]
bad = [r for r in sorted_r if r['d20_wr'] < 40]
msg += '<b>결론:</b>\n'
if good:
    msg += '유의미: ' + ', '.join(r['test'] for r in good) + '\n'
else:
    msg += '55%+ 시그널 없음\n'
if bad:
    msg += '회피용: ' + ', '.join(r['test'] for r in bad)

send_tg(msg)
print('\n텔레그램 전송 완료')

pd.DataFrame(all_results).to_csv(str(PROJECT/'backtest'/'realtime_signal_eda.csv'), index=False, encoding='utf-8-sig')
print('저장: backtest/realtime_signal_eda.csv')
