"""
상세 텔레그램 메시지 전송 (편입/편출 포함)
"""
import pandas as pd
import numpy as np
from pykrx import stock
from datetime import datetime, timedelta
from pathlib import Path
import requests
import json
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

# ============================================================
# 설정
# ============================================================
CACHE_DIR = Path('data_cache')
OUTPUT_DIR = Path('output')
HISTORY_FILE = CACHE_DIR / 'portfolio_history.json'

# ============================================================
# 날짜 자동 감지
# ============================================================
today = stock.get_nearest_business_day_in_a_week()
print(f"기준일: {today}")

# 시장 지수
start_date = (datetime.strptime(today, '%Y%m%d') - timedelta(days=7)).strftime('%Y%m%d')
kospi_idx = stock.get_index_ohlcv(start_date, today, '1001')
kosdaq_idx = stock.get_index_ohlcv(start_date, today, '2001')

kospi_close = kospi_idx.iloc[-1, 3]
kospi_prev = kospi_idx.iloc[-2, 3] if len(kospi_idx) > 1 else kospi_close
kospi_chg = ((kospi_close / kospi_prev) - 1) * 100

kosdaq_close = kosdaq_idx.iloc[-1, 3]
kosdaq_prev = kosdaq_idx.iloc[-2, 3] if len(kosdaq_idx) > 1 else kosdaq_close
kosdaq_chg = ((kosdaq_close / kosdaq_prev) - 1) * 100

if kospi_chg > 1:
    market_status = "🟢 상승장"
elif kospi_chg < -1:
    market_status = "🔴 하락장"
else:
    market_status = "🟡 보합장"

# ============================================================
# 포트폴리오 결과 로드
# ============================================================
a = pd.read_csv(OUTPUT_DIR / 'portfolio_2026_01_strategy_a.csv', encoding='utf-8-sig')
b = pd.read_csv(OUTPUT_DIR / 'portfolio_2026_01_strategy_b.csv', encoding='utf-8-sig')

a['종목코드'] = a['종목코드'].astype(str).str.zfill(6)
b['종목코드'] = b['종목코드'].astype(str).str.zfill(6)

set_a = set(a['종목코드'])
set_b = set(b['종목코드'])
common_today = set_a & set_b

# 종목명 딕셔너리
ticker_names = {}
for _, row in a.iterrows():
    ticker_names[row['종목코드']] = row['종목명']
for _, row in b.iterrows():
    ticker_names[row['종목코드']] = row['종목명']

# ============================================================
# 이전 결과 로드 (편입/편출 비교용)
# ============================================================
def load_previous_results():
    """이전 포트폴리오 결과 로드"""
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def save_current_results():
    """현재 결과를 히스토리에 저장"""
    history = {
        'date': today,
        'strategy_a': list(set_a),
        'strategy_b': list(set_b),
        'common': list(common_today),
        'ticker_names': ticker_names
    }
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

previous = load_previous_results()

# 편입/편출 계산
if previous and previous.get('date') != today:
    prev_common = set(previous.get('common', []))
    prev_a = set(previous.get('strategy_a', []))
    prev_b = set(previous.get('strategy_b', []))
    prev_names = previous.get('ticker_names', {})

    # 공통 종목 변화
    common_added = common_today - prev_common
    common_removed = prev_common - common_today

    # 전략별 변화
    a_added = set_a - prev_a
    a_removed = prev_a - set_a
    b_added = set_b - prev_b
    b_removed = prev_b - set_b

    has_changes = True
    print(f"이전 기준일: {previous.get('date')}")
    print(f"공통 편입: {len(common_added)}개, 편출: {len(common_removed)}개")
else:
    has_changes = False
    common_added = set()
    common_removed = set()
    a_added = set()
    a_removed = set()
    b_added = set()
    b_removed = set()
    prev_names = {}

# ============================================================
# 시가총액/OHLCV 로드
# ============================================================
market_cap_files = list(CACHE_DIR.glob(f'market_cap_ALL_{today}.parquet'))
if market_cap_files:
    market_cap = pd.read_parquet(market_cap_files[0])
else:
    market_cap_files = sorted(CACHE_DIR.glob('market_cap_ALL_*.parquet'))
    market_cap = pd.read_parquet(market_cap_files[-1]) if market_cap_files else pd.DataFrame()

ohlcv_files = sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'))
ohlcv = pd.read_parquet(ohlcv_files[-1]) if ohlcv_files else pd.DataFrame()

# ============================================================
# 기술 지표 함수
# ============================================================
def calc_rsi(prices, period=14):
    if len(prices) < period + 1:
        return np.nan
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]

def calc_52week_position(prices):
    if len(prices) < 250:
        return np.nan
    high_52w = prices.tail(250).max()
    current = prices.iloc[-1]
    from_high = (current / high_52w - 1) * 100
    return from_high

def get_stock_info(ticker):
    """종목 정보 조회"""
    ticker_str = str(ticker).zfill(6)

    try:
        price = market_cap.loc[ticker_str].iloc[0]
        cap = market_cap.loc[ticker_str].iloc[1] / 100000000
        market_type = market_cap.loc[ticker_str]['market']
    except:
        price, cap, market_type = 0, 0, 'KOSDAQ'

    if ticker_str in ohlcv.columns:
        prices = ohlcv[ticker_str].dropna()
        rsi = calc_rsi(prices)
        from_high = calc_52week_position(prices)
    else:
        rsi, from_high = np.nan, np.nan

    rsi_str = f"RSI {rsi:.0f}" if pd.notna(rsi) else "RSI -"
    from_high = from_high if pd.notna(from_high) else 0

    return {
        'price': price,
        'cap': cap,
        'market': market_type,
        'rsi_str': rsi_str,
        'from_high': from_high
    }

# ============================================================
# 메시지 생성
# ============================================================

# 메시지 1: 개요 + 공통종목 + 편입/편출
msg1 = f"""🇰🇷 한국주식 퀀트 포트폴리오 v3.0
━━━━━━━━━━━━━━━━━━━━━━━━━
📅 {today[:4]}-{today[4:6]}-{today[6:]} | 유니버스 718개
🚦 시장: {market_status}
   KOSPI {kospi_close:,.0f} ({kospi_chg:+.1f}%)
   KOSDAQ {kosdaq_close:,.0f} ({kosdaq_chg:+.1f}%)
━━━━━━━━━━━━━━━━━━━━━━━━━

📋 전략 구성
🔴 전략A: 마법공식 (이익수익률 + ROIC)
🔵 전략B: 멀티팩터 (밸류+퀄리티+모멘텀)

━━━━━━━━━━━━━━━━━━━━━━━━━

⭐ 공통 종목 ({len(common_today)}개)
"""

# 공통 종목 상세
common_details = []
for ticker in common_today:
    name = ticker_names.get(ticker, ticker)
    rank_a = a[a['종목코드'] == ticker]['마법공식_순위'].values
    rank_b = b[b['종목코드'] == ticker]['멀티팩터_순위'].values
    rank_a = rank_a[0] if len(rank_a) > 0 else 99
    rank_b = rank_b[0] if len(rank_b) > 0 else 99
    info = get_stock_info(ticker)
    common_details.append({
        'ticker': ticker,
        'name': name,
        'rank_a': rank_a,
        'rank_b': rank_b,
        'avg_rank': (rank_a + rank_b) / 2,
        **info
    })

common_details.sort(key=lambda x: x['avg_rank'])

for d in common_details:
    is_new = "🆕" if d['ticker'] in common_added else ""
    msg1 += f"""──────────────────────
{is_new}{d['name']} ({d['ticker']})
   💰 {d['price']:,.0f}원 | 시총 {d['cap']:,.0f}억
   📊 A {d['rank_a']:.0f}위 / B {d['rank_b']:.0f}위
   {d['rsi_str']} | 고점대비 {d['from_high']:.0f}%
"""

# 편입/편출 정보
if has_changes and (common_added or common_removed):
    msg1 += """━━━━━━━━━━━━━━━━━━━━━━━━━

📊 공통종목 변화
"""
    if common_removed:
        msg1 += "🔻 편출:\n"
        for ticker in common_removed:
            name = prev_names.get(ticker, ticker_names.get(ticker, ticker))
            # 왜 편출됐는지 상세 분석
            reasons = []
            if ticker in set_a:
                rank_a = a[a['종목코드'] == ticker]['마법공식_순위'].values
                reasons.append(f"A {rank_a[0]:.0f}위" if len(rank_a) > 0 else "A유지")
            else:
                reasons.append("A 30위밖")
            if ticker in set_b:
                rank_b = b[b['종목코드'] == ticker]['멀티팩터_순위'].values
                reasons.append(f"B {rank_b[0]:.0f}위" if len(rank_b) > 0 else "B유지")
            else:
                reasons.append("B 30위밖")
            msg1 += f"   • {name}: {', '.join(reasons)}\n"

    if common_added:
        msg1 += "🔺 편입:\n"
        for ticker in common_added:
            name = ticker_names.get(ticker, ticker)
            msg1 += f"   • {name}\n"

msg1 += "━━━━━━━━━━━━━━━━━━━━━━━━━"

# 메시지 2: 전략 A
msg2 = f"""🔴 전략 A - 마법공식 TOP 15
━━━━━━━━━━━━━━━━━━━━━━━━━
이익수익률↑ + 투하자본수익률↑

"""

for i, (_, row) in enumerate(a.head(15).iterrows()):
    ticker = row['종목코드']
    name = row['종목명']
    info = get_stock_info(ticker)
    is_common = "⭐" if ticker in common_today else ""
    is_new = "🆕" if ticker in a_added else ""

    msg2 += f"""{i+1}. {is_new}{name} ({ticker}) {is_common}
   💰{info['price']:,.0f}원 | {info['rsi_str']} | 고점{info['from_high']:.0f}%
"""

if a_removed:
    msg2 += "\n🔻 편출: "
    removed_names = [prev_names.get(t, t) for t in list(a_removed)[:5]]
    msg2 += ", ".join(removed_names)
    if len(a_removed) > 5:
        msg2 += f" 외 {len(a_removed)-5}개"

msg2 += "\n━━━━━━━━━━━━━━━━━━━━━━━━━"

# 메시지 3: 전략 B
msg3 = f"""🔵 전략 B - 멀티팩터 TOP 15
━━━━━━━━━━━━━━━━━━━━━━━━━
밸류40% + 퀄리티40% + 모멘텀20%

"""

for i, (_, row) in enumerate(b.head(15).iterrows()):
    ticker = row['종목코드']
    name = row['종목명']
    info = get_stock_info(ticker)
    is_common = "⭐" if ticker in common_today else ""
    is_new = "🆕" if ticker in b_added else ""

    msg3 += f"""{i+1}. {is_new}{name} ({ticker}) {is_common}
   💰{info['price']:,.0f}원 | {info['rsi_str']} | 고점{info['from_high']:.0f}%
"""

if b_removed:
    msg3 += "\n🔻 편출: "
    removed_names = [prev_names.get(t, t) for t in list(b_removed)[:5]]
    msg3 += ", ".join(removed_names)
    if len(b_removed) > 5:
        msg3 += f" 외 {len(b_removed)-5}개"

msg3 += """
━━━━━━━━━━━━━━━━━━━━━━━━━

💡 범례
⭐ = 공통종목 (A+B 모두 선정)
🆕 = 신규 편입
━━━━━━━━━━━━━━━━━━━━━━━━━"""

# ============================================================
# 텔레그램 전송
# ============================================================
url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'

r1 = requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'text': msg1})
print(f'메시지 1 (공통+변화): {r1.status_code}')

r2 = requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'text': msg2})
print(f'메시지 2 (전략A): {r2.status_code}')

r3 = requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'text': msg3})
print(f'메시지 3 (전략B): {r3.status_code}')

# 현재 결과 저장 (다음 비교용)
save_current_results()
print(f'\n히스토리 저장: {HISTORY_FILE}')

# 요약 출력
print(f'\n=== 요약 ===')
print(f'공통종목: {len(common_today)}개')
if has_changes:
    print(f'공통 편입: {len(common_added)}개, 편출: {len(common_removed)}개')
    print(f'전략A 편입: {len(a_added)}개, 편출: {len(a_removed)}개')
    print(f'전략B 편입: {len(b_added)}개, 편출: {len(b_removed)}개')
