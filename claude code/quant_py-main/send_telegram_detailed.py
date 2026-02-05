"""
상세 텔레그램 메시지 전송 (편입/편출 + 종목 인사이트 포함)
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
# Claude의 최종 순위 판단 (공통 종목 대상)
# 2026-02-05 기준 종합 분석 반영
# ============================================================
# 판단 기준 (종합적):
# 1. 전략 A/B 순위 (퀀트 점수)
# 2. 기술적 위치 (52주 위치, MA배열, RSI)
# 3. 거래량 분석 (20일 평균 대비)
# 4. 최신 뉴스/촉매제
# 5. 리스크 요인

CLAUDE_FINAL_RANKING = {
    # 2026-02-05 기준 (2월 4일 데이터 기반)
    # Claude 종합 판단: 진입점수(RSI+52주위치+거래량+일봉) + 뉴스조정 + 전략순위

    '119850': {  # 지엔씨에너지 ★1위
        'rank': 1,
        'grade': 'S',
        'entry_score': 75,
        'reason': '[최적 진입타이밍] 거래량 2.75배 급증! RSI 62.8 적정구간. 52주고점대비 -14.8%. 당일 +9.78% 급등! AI 데이터센터 비상발전기 국내 1위. SK울산 수주.',
        'risk': '중소형주 변동성, 전략순위 중위권 (A 21위/B 23위)'
    },
    '204620': {  # 글로벌텍스프리 ★2위 (신규편입)
        'rank': 2,
        'grade': 'S',
        'entry_score': 75,
        'reason': '[신규편입] 거래량 3.05배 폭발! 52주고점대비 -33.8% 저점매수 기회. 당일 +5.07% 급등. 면세사업 회복, 중국 관광객 증가 기대.',
        'risk': 'RSI 83.9 과매수 주의, 단기 차익실현 가능'
    },
    '123330': {  # 제닉 ★3위 (신규편입)
        'rank': 3,
        'grade': 'S',
        'entry_score': 75,
        'reason': '[신규편입] 전략A 2위! 52주고점대비 -50.1% 역대급 저점! 거래량 2.09배 급증. K-뷰티 화장품/마스크팩 전문. ROE 52.4% 초고수익.',
        'risk': 'RSI 69.7 과열 접근, 당일 -2.65% 조정'
    },
    '018290': {  # 브이티 ★4위
        'rank': 4,
        'grade': 'A',
        'entry_score': 60,
        'reason': '[전략A 1위] 52주고점대비 -55.9% 역대급 저점 매수기회! K-뷰티 대장주. 당일 +0.90% 상승. 마법공식 최고 수익률.',
        'risk': 'RSI 74.3 과매수, 거래량 평균 이하(0.71x), KS인더스트리 투자 우려'
    },
    '402340': {  # SK스퀘어 ★5위
        'rank': 5,
        'grade': 'A',
        'entry_score': 55,
        'reason': '[AI반도체 간접투자] SK하이닉스 20% 지분! 거래량 1.67배 증가. 당일 +4.21% 급등. 정배열 완벽. 주주환원 확대 기대.',
        'risk': 'RSI 71.8 과매수, 52주고점 근접(-2.1%), 지주사 디스카운트'
    },
    '001060': {  # JW중외제약 ★6위
        'rank': 6,
        'grade': 'A',
        'entry_score': 55,
        'reason': '[바이오 안정주] 거래량 1.60배 증가. 당일 +6.48% 급등! 52주고점 근처(-1.8%). 영업이익 971억, ROE 17.7%.',
        'risk': 'RSI 75.6 과매수 주의, 전략순위 중하위 (A 18위/B 28위)'
    },
    '124500': {  # 아이티센글로벌 ★7위
        'rank': 7,
        'grade': 'B+',
        'entry_score': 45,
        'reason': '[금값 수혜] 전략B 3위! 한국금거래소 운영. 52주고점대비 -8.4%. 당일 +0.79% 소폭 상승.',
        'risk': 'RSI 72.7 과매수, 거래량 평균 이하(0.36x), 진입 모멘텀 약함'
    },
    '000660': {  # SK하이닉스 ★8위
        'rank': 8,
        'grade': 'B',
        'entry_score': 40,
        'reason': '[AI반도체 대장] HBM 글로벌 1위. 2026년 영업이익 100조+ 전망. 실적 확실성 최고.',
        'risk': '진입타이밍 비추! RSI 67.4에 당일 -0.77% 하락. 거래량 평균 이하(0.80x). 52주고점 근접(-3.3%). 고가 부담 90만원대.'
    },
}

# ============================================================
# 종목 인사이트 데이터베이스
# ============================================================
STOCK_INSIGHTS = {
    # ===== 공통 종목 =====
    '419530': {
        'name': 'SAMG엔터',
        'sector': '애니메이션/캐릭터',
        'summary': '캐치! 티니핑 대히트로 국내 최대 3D 애니메이션 제작사',
        'highlight': '티니핑 글로벌 확장 + 흑자전환',
        'why_selected': '캐릭터 IP 수익성 급증, 라이선스 매출 확대'
    },
    '018290': {
        'name': '브이티',
        'sector': 'K-뷰티',
        'summary': 'VT코스메틱 운영, 일본/미국/중국 글로벌 확장 중',
        'highlight': '영업이익률 29%, 화장품 매출 37%↑',
        'why_selected': '고마진 화장품 + 해외 성장 가속화'
    },
    '383220': {
        'name': 'F&F',
        'sector': '패션',
        'summary': 'MLB, 디스커버리 브랜드 보유, 중국 매출 51%',
        'highlight': '중국 MLB 성공 + 디스커버리 확장',
        'why_selected': '중국 소비 회복 시 실적 레버리지 기대'
    },
    '402340': {
        'name': 'SK스퀘어',
        'sector': '투자지주',
        'summary': 'SK하이닉스 20% 지분 보유 투자회사',
        'highlight': 'SK하이닉스 사상최대 실적 수혜',
        'why_selected': 'AI 반도체 호황으로 NAV 급증'
    },
    '204620': {
        'name': '글로벌텍스프리',
        'sector': '택스리펀드',
        'summary': '외국인 세금환급 서비스 국내 1위',
        'highlight': '영업이익 40%↑, 일본/싱가포르 진출',
        'why_selected': '방한 외국인 증가 + 해외 시장 확장'
    },
    '039130': {
        'name': '하나투어',
        'sector': '여행',
        'summary': '국내 최대 종합여행사, 2만개 상품 운영',
        'highlight': '창사 이래 최대 실적, 영업이익 1000억↑',
        'why_selected': '해외여행 회복 + 무차입 우량 재무'
    },
    '033500': {
        'name': '동성화인텍',
        'sector': 'LNG 단열재',
        'summary': 'LNG 운반선 단열재/보냉재 국내 1위',
        'highlight': '2026년까지 수주물량 확보, 영업이익률 12%',
        'why_selected': 'LNG 운반선 호황 + 중국 시장 진출 기대'
    },
    '119850': {
        'name': '지엔씨에너지',
        'sector': '에너지/발전설비',
        'summary': '데이터센터 비상발전기 국내 1위',
        'highlight': '영업이익 115%↑, AI 데이터센터 수혜',
        'why_selected': 'AI 인프라 투자 확대 + 신재생에너지'
    },
    '124500': {
        'name': '아이티센글로벌',
        'sector': 'IT/금거래',
        'summary': '한국금거래소 운영, 디지털 금 플랫폼',
        'highlight': '영업이익 293%↑, 금값 상승 수혜',
        'why_selected': '금 안전자산 수요 + 스테이블코인 사업'
    },
    '123330': {
        'name': '제닉',
        'sector': 'K-뷰티/화장품',
        'summary': '마스크팩/화장품 ODM 전문기업, 글로벌 수출',
        'highlight': 'ROE 52.4%, 영업이익률 21.7%',
        'why_selected': '전략A 2위! 52주 저점 -50% 역발상 매수 기회'
    },
    '000660': {
        'name': 'SK하이닉스',
        'sector': 'AI반도체/메모리',
        'summary': 'HBM 글로벌 1위, AI 반도체 대장주',
        'highlight': '2026년 영업이익 100조+ 전망',
        'why_selected': 'AI 슈퍼사이클 최대 수혜, 실적 확실성'
    },
    '001060': {
        'name': 'JW중외제약',
        'sector': '바이오/제약',
        'summary': '제네릭의약품 전문, 안정적 실적',
        'highlight': '영업이익 971억, ROE 17.7%',
        'why_selected': '바이오 섹터 안정주, 배당 매력'
    },

    # ===== 전략 A TOP 10 =====
    '200670': {
        'name': '휴메딕스',
        'sector': '필러/히알루론산',
        'summary': '히알루론산 필러 엘라비에 글로벌 수출',
        'highlight': '필러 수출 40% 증가, 브라질/중국 확대',
        'why_selected': '고마진 필러 사업 + 신제품 출시 예정'
    },
    '033100': {
        'name': '제룡전기',
        'sector': '변압기/전력설비',
        'summary': '배전 변압기 전문, 미국 수출 80%',
        'highlight': '미국 전력망 교체 수요 수혜',
        'why_selected': '미국 인프라 투자 + 2026년까지 수주 확보'
    },
    '067160': {
        'name': 'SOOP',
        'sector': '스트리밍',
        'summary': '아프리카TV 운영, 글로벌 플랫폼 확장',
        'highlight': '매출 16%↑, 글로벌 원플랫폼 통합',
        'why_selected': '스트리밍 성장 + e스포츠 콘텐츠 강화'
    },
    '462870': {
        'name': '시프트업',
        'sector': '게임',
        'summary': '니케/스텔라블레이드 개발사',
        'highlight': '영업이익률 65%, 글로벌 IP 가치',
        'why_selected': '고수익 게임 IP + 신작 파이프라인'
    },
    '035900': {
        'name': 'JYP Ent.',
        'sector': '엔터테인먼트',
        'summary': '스트레이키즈, 트와이스, 있지 보유',
        'highlight': '분기 최고 매출 2326억, 빌보드 1위',
        'why_selected': '글로벌 K-POP 팬덤 + 월드투어 확대'
    },
    '250060': {
        'name': '모비스',
        'sector': 'AI/핵융합',
        'summary': 'EPICS 기반 초정밀 제어시스템 전문',
        'highlight': 'ITER 프로젝트 참여, 스마트팩토리',
        'why_selected': '핵융합 기술력 + AI 솔루션 성장'
    },

    # ===== 전략 B TOP 10 =====
    '278470': {
        'name': '에이피알',
        'sector': '뷰티디바이스',
        'summary': '메디큐브 에이지알 뷰티기기 글로벌 500만대 판매',
        'highlight': '매출 122%↑, 영업이익 253%↑',
        'why_selected': '홈뷰티 시장 폭발 + 해외매출 77%'
    },
    '084670': {
        'name': '동양피스톤',
        'sector': '자동차부품',
        'summary': '엔진 피스톤 글로벌 4위, 현대/GM/포드 납품',
        'highlight': '수소차 인클로저 독점 공급',
        'why_selected': '완성차 회복 + 수소차 부품 진출'
    },
    '036620': {
        'name': '감성코퍼레이션',
        'sector': '아웃도어패션',
        'summary': '스노우피크 어패럴 라이선스 운영',
        'highlight': '매출 30%↑, 영업이익 22%↑',
        'why_selected': '아웃도어 트렌드 + 해외 확장'
    },
    '108490': {
        'name': '로보티즈',
        'sector': '로봇부품',
        'summary': '로봇 액추에이터(다이나믹셀) 글로벌 톱티어',
        'highlight': '휴머노이드 로봇 핵심부품, 흑자전환',
        'why_selected': 'AI 로봇 시대 핵심 부품 공급'
    },
    '000660': {
        'name': 'SK하이닉스',
        'sector': 'AI반도체',
        'summary': 'HBM 글로벌 1위, 엔비디아 주요 공급사',
        'highlight': '영업이익 47조↑, 2026년 100조 전망',
        'why_selected': 'AI 메모리 슈퍼사이클 최대 수혜'
    },
    '043260': {
        'name': '성호전자',
        'sector': '전자부품',
        'summary': 'SMPS/필름콘덴서 전문, 삼성/LG 납품',
        'highlight': '전기차/ESS 콘덴서 성장 기대',
        'why_selected': '친환경 시장 확대 + AI 인프라'
    },
    '008770': {
        'name': '호텔신라',
        'sector': '면세점/호텔',
        'summary': '신라면세점 운영, 인천공항 철수로 체질개선',
        'highlight': '영업이익 341%↑ 전망, 손실사업 정리',
        'why_selected': '방한 외국인 증가 + 수익성 개선'
    },
    '336570': {
        'name': '원텍',
        'sector': '의료기기',
        'summary': '레이저 의료기기 전문, 피부과/성형외과 시장',
        'highlight': '레이저 치료기 수출 확대',
        'why_selected': '의료미용 시장 성장'
    },
    '402340': {
        'name': 'SK스퀘어',
        'sector': '투자지주',
        'summary': 'SK하이닉스 20% 지분 보유 투자회사',
        'highlight': 'SK하이닉스 사상최대 실적 수혜',
        'why_selected': 'AI 반도체 호황으로 NAV 급증'
    },
    '001060': {
        'name': 'JW중외제약',
        'sector': '바이오/제약',
        'summary': '국내 중견 제약사, 다양한 의약품 포트폴리오',
        'highlight': '영업이익 971억, ROE 17.7%',
        'why_selected': '안정적 실적 + 바이오 성장동력'
    },
}

# ============================================================
# 날짜 자동 감지 (최신 거래일 찾기)
# ============================================================
def get_latest_trading_date():
    """최근 거래일 찾기"""
    now = datetime.now()
    for i in range(10):
        date = (now - timedelta(days=i)).strftime('%Y%m%d')
        try:
            df = stock.get_market_cap(date, market='KOSPI')
            if not df.empty and df.iloc[:, 0].sum() > 0:
                return date
        except:
            continue
    return stock.get_nearest_business_day_in_a_week()

today = get_latest_trading_date()
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
    """종목 정보 조회 - pykrx 실시간 조회"""
    ticker_str = str(ticker).zfill(6)

    # pykrx에서 실시간 시세 조회
    try:
        # 최근 1년 OHLCV 조회
        start = (datetime.strptime(today, '%Y%m%d') - timedelta(days=365)).strftime('%Y%m%d')
        ohlcv_data = stock.get_market_ohlcv(start, today, ticker_str)

        if not ohlcv_data.empty:
            price = ohlcv_data.iloc[-1, 3]  # 종가

            # 시가총액 조회
            cap_df = stock.get_market_cap(today, today, ticker_str)
            if not cap_df.empty:
                cap = cap_df.iloc[0, 0] / 100000000  # 시가총액 (억원)
            else:
                cap = 0

            # RSI 계산
            prices = ohlcv_data.iloc[:, 3]  # 종가
            rsi = calc_rsi(prices)

            # 52주 고점 대비
            high_52w = ohlcv_data.iloc[:, 1].max()  # 고가
            from_high = (price / high_52w - 1) * 100 if high_52w > 0 else 0
        else:
            price, cap, rsi, from_high = 0, 0, np.nan, 0
    except Exception as e:
        print(f"  시세 조회 실패 {ticker_str}: {e}")
        price, cap, rsi, from_high = 0, 0, np.nan, 0

    # 시장 구분
    try:
        market_type = 'KOSPI' if ticker_str in stock.get_market_ticker_list(today, market='KOSPI') else 'KOSDAQ'
    except:
        market_type = 'KOSDAQ'

    rsi_str = f"RSI {rsi:.0f}" if pd.notna(rsi) else "RSI -"
    from_high = from_high if pd.notna(from_high) else 0

    return {
        'price': price,
        'cap': cap,
        'market': market_type,
        'rsi_str': rsi_str,
        'from_high': from_high
    }

def get_insight(ticker):
    """종목 인사이트 조회"""
    ticker_str = str(ticker).zfill(6)
    return STOCK_INSIGHTS.get(ticker_str, {})

def get_claude_ranking(ticker):
    """Claude의 최종 순위 조회"""
    ticker_str = str(ticker).zfill(6)
    return CLAUDE_FINAL_RANKING.get(ticker_str, {'rank': 99, 'grade': '-', 'reason': '', 'risk': ''})

# ============================================================
# 메시지 생성 (고객 친화적)
# ============================================================

# 메시지 1: 인사 + 공통종목 상세 (Claude 최종 순위)
msg1 = f"""안녕하세요! 오늘의 퀀트 포트폴리오입니다 📊

━━━━━━━━━━━━━━━━━━━━━━━━━
📅 {today[:4]}년 {today[4:6]}월 {today[6:]}일
{market_status}
• 코스피 {kospi_close:,.0f} ({kospi_chg:+.1f}%)
• 코스닥 {kosdaq_close:,.0f} ({kosdaq_chg:+.1f}%)
━━━━━━━━━━━━━━━━━━━━━━━━━

💡 전략 소개
🔴 전략A 마법공식: 싸고 돈 잘 버는 기업
🔵 전략B 멀티팩터: 가치+실적+상승흐름

━━━━━━━━━━━━━━━━━━━━━━━━━

🏆 Claude 최종 추천 순위
공통 종목 {len(common_today)}개를 분석하여 순위 선정
(전략순위 + 실적성장 + 섹터모멘텀 + 리스크 종합)
"""

# 공통 종목 상세 (Claude 최종 순위로 정렬)
common_details = []
for ticker in common_today:
    name = ticker_names.get(ticker, ticker)
    rank_a = a[a['종목코드'] == ticker]['마법공식_순위'].values
    rank_b = b[b['종목코드'] == ticker]['멀티팩터_순위'].values
    rank_a = rank_a[0] if len(rank_a) > 0 else 99
    rank_b = rank_b[0] if len(rank_b) > 0 else 99
    info = get_stock_info(ticker)
    insight = get_insight(ticker)
    claude_rank = get_claude_ranking(ticker)
    common_details.append({
        'ticker': ticker,
        'name': name,
        'rank_a': rank_a,
        'rank_b': rank_b,
        'avg_rank': (rank_a + rank_b) / 2,
        'insight': insight,
        'claude_rank': claude_rank,
        **info
    })

# Claude 최종 순위로 정렬
common_details.sort(key=lambda x: x['claude_rank']['rank'])

for d in common_details:
    is_new = "🆕 " if d['ticker'] in common_added else ""
    insight = d['insight']
    claude = d['claude_rank']
    sector = insight.get('sector', '')

    # 등급에 따른 이모지
    grade_emoji = {'S': '🥇', 'A': '🥈', 'B+': '🥉', 'B': '📊'}.get(claude['grade'], '📊')

    msg1 += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━
{grade_emoji} {claude['rank']}위 [{claude['grade']}등급] {is_new}{d['name']}
({d['ticker']}) [{sector}]
━━━━━━━━━━━━━━━━━━━━━━━━━
💰 {d['price']:,.0f}원 | 시총 {d['cap']:,.0f}억
📊 전략A {d['rank_a']:.0f}위 / 전략B {d['rank_b']:.0f}위
📈 {d['rsi_str']} | 52주고점 대비 {d['from_high']:.0f}%

📝 선정 이유:
{claude['reason']}

⚠️ 리스크: {claude['risk']}"""

# 편입/편출 정보
if has_changes and (common_added or common_removed):
    msg1 += """

━━━━━━━━━━━━━━━━━━━━━━━━━
📊 어제 대비 변화
━━━━━━━━━━━━━━━━━━━━━━━━━"""
    if common_removed:
        msg1 += "\n🔻 공통종목 편출:"
        for ticker in common_removed:
            name = prev_names.get(ticker, ticker_names.get(ticker, ticker))
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
            msg1 += f"\n  • {name} ({', '.join(reasons)})"

    if common_added:
        msg1 += "\n\n🔺 공통종목 신규 편입:"
        for ticker in common_added:
            name = ticker_names.get(ticker, ticker)
            insight = get_insight(ticker)
            summary = insight.get('summary', '')
            msg1 += f"\n  • {name}"
            if summary:
                msg1 += f" - {summary[:30]}..."

msg1 += """

━━━━━━━━━━━━━━━━━━━━━━━━━
📌 등급 기준
S등급: 최우선 매수 고려
A등급: 적극 매수 고려
B+등급: 매수 고려
━━━━━━━━━━━━━━━━━━━━━━━━━"""

# 메시지 2: 전략 A TOP 10 (인사이트 포함)
msg2 = f"""🔴 전략 A - 마법공식 TOP 10
━━━━━━━━━━━━━━━━━━━━━━━━━
"싸게 사서 비싸게 파는" 가치투자 전략
이익수익률↑ + 투하자본수익률↑

"""

for i, (_, row) in enumerate(a.head(10).iterrows()):
    ticker = row['종목코드']
    name = row['종목명']
    info = get_stock_info(ticker)
    insight = get_insight(ticker)
    is_common = "⭐" if ticker in common_today else ""
    is_new = "🆕" if ticker in a_added else ""

    sector = insight.get('sector', '')
    summary = insight.get('summary', '')

    msg2 += f"""{i+1}. {is_new}{name} {is_common}"""
    if sector:
        msg2 += f" [{sector}]"
    msg2 += f"""
   💰 {info['price']:,.0f}원 | {info['rsi_str']}"""
    if summary:
        msg2 += f"\n   💡 {summary[:35]}..."
    msg2 += "\n"

if a_removed:
    msg2 += "\n🔻 편출: "
    removed_names = [prev_names.get(t, t) for t in list(a_removed)[:5]]
    msg2 += ", ".join(removed_names)
    if len(a_removed) > 5:
        msg2 += f" 외 {len(a_removed)-5}개"

msg2 += "\n━━━━━━━━━━━━━━━━━━━━━━━━━"

# 메시지 3: 전략 B TOP 10 (인사이트 포함)
msg3 = f"""🔵 전략 B - 멀티팩터 TOP 10
━━━━━━━━━━━━━━━━━━━━━━━━━
균형 잡힌 팩터 투자 전략
밸류40% + 퀄리티40% + 모멘텀20%

"""

for i, (_, row) in enumerate(b.head(10).iterrows()):
    ticker = row['종목코드']
    name = row['종목명']
    info = get_stock_info(ticker)
    insight = get_insight(ticker)
    is_common = "⭐" if ticker in common_today else ""
    is_new = "🆕" if ticker in b_added else ""

    sector = insight.get('sector', '')
    summary = insight.get('summary', '')

    msg3 += f"""{i+1}. {is_new}{name} {is_common}"""
    if sector:
        msg3 += f" [{sector}]"
    msg3 += f"""
   💰 {info['price']:,.0f}원 | {info['rsi_str']}"""
    if summary:
        msg3 += f"\n   💡 {summary[:35]}..."
    msg3 += "\n"

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
━━━━━━━━━━━━━━━━━━━━━━━━━

📌 투자 유의사항
• 본 정보는 투자 권유가 아닙니다
• 투자 결정은 본인 판단하에 하시기 바랍니다
• 분기별 리밸런싱 권장 (3/6/9/12월)
━━━━━━━━━━━━━━━━━━━━━━━━━"""

# ============================================================
# 텔레그램 전송
# ============================================================
url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'

r1 = requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'text': msg1})
print(f'메시지 1 (공통+인사이트): {r1.status_code}')

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
