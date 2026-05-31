"""ETF 시스템 실현성 프로브 (회사 PC 전용 — pykrx 라이브 필요).

집 IP는 KRX 차단이라 여기선 실패함. 회사 PC(주식 파이프라인 도는 환경)에서 실행할 것.
목적: ETF 데이터가 (1) 무엇이 (2) 과거까지 (3) 어떤 컬럼으로 나오는지 '확정'한다.
모든 호출 순차 + 1초 sleep (CLAUDE.md pykrx 규칙 준수).

실행: python etf_research/etf_probe.py
결과: etf_research/_probe_out/ 에 샘플 parquet/csv + 콘솔 리포트
"""
import sys, time, json
from pathlib import Path
import pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
# KRX 2026-02-27~ 로그인 필수. pykrx 호출 전 반드시 login (빈응답=IP차단 아님)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import krx_auth
if not krx_auth.login():
    print('[중단] KRX 로그인 실패 — config.py의 KRX_USER_ID/PASSWORD 확인'); sys.exit(1)
import pykrx.stock as stock

OUT = Path(__file__).parent / '_probe_out'
OUT.mkdir(exist_ok=True)
SLEEP = 1.0  # pykrx 순차 + 1초

def d0_60(base):
    return (pd.Timestamp(base) - pd.Timedelta(days=90)).strftime('%Y%m%d')


def sec(t): print('\n' + '='*70 + f'\n{t}\n' + '='*70, flush=True)
def call(label, fn):
    t0 = time.time()
    try:
        r = fn(); print(f'[OK] {label} ({time.time()-t0:.1f}s)', flush=True); return r
    except Exception as e:
        print(f'[FAIL] {label}: {type(e).__name__}: {str(e)[:140]}', flush=True); return None
    finally:
        time.sleep(SLEEP)


# 최근 영업일 자동 (today 기준 가장 가까운 영업일)
BASE = stock.get_nearest_business_day_in_a_week()
print(f'기준 영업일: {BASE}')

# 1) 전체 ETF 유니버스
sec('1) ETF 유니버스')
tickers = call('get_etf_ticker_list', lambda: stock.get_etf_ticker_list(BASE)) or []
print(f'총 ETF 수: {len(tickers)}')
names = {}
active = []
for tk in tickers[:0]:  # 이름은 아래 일괄로
    pass
# 이름 일괄(티커별 1콜은 과함 → price_change_by_ticker가 이름 포함하는지 확인)

# 2) 터지는 ETF — 전 종목 등락/거래량/거래대금을 '1콜'로 (핵심 효율)
sec('2) 거래대금/등락 급증 ETF (1콜로 전 종목)')
# 최근 5영업일 구간
import datetime as dt
d0 = (pd.Timestamp(BASE) - pd.Timedelta(days=10)).strftime('%Y%m%d')
chg = call('get_etf_price_change_by_ticker', lambda: stock.get_etf_price_change_by_ticker(d0, BASE))
if chg is not None:
    print('컬럼:', list(chg.columns))
    print('shape:', chg.shape)
    chg.to_parquet(OUT / 'price_change_sample.parquet')
    # 거래대금 컬럼 추정 정렬
    for vc in ['거래대금', '등락률']:
        if vc in chg.columns:
            print(f'\n--- {vc} 상위 10 ---')
            top = chg.sort_values(vc, ascending=False).head(10)
            print(top.to_string()[:1500])

# 3) ETF OHLCV + NAV (과거 시계열 가능?) — 자금흐름 계산용 컬럼 탐색
sec('3) ETF OHLCV/NAV 과거 시계열 + 순자산총액/상장좌수 존재 여부')
sample_tk = tickers[0] if tickers else '069500'  # KODEX 200
ohlcv = call(f'get_etf_ohlcv_by_date({sample_tk}, 60일)',
             lambda: stock.get_etf_ohlcv_by_date(d0_60(BASE), BASE, sample_tk))
if ohlcv is not None:
    print('OHLCV 컬럼:', list(ohlcv.columns))
    print('행수(과거 시계열 OK?):', len(ohlcv))
    print(ohlcv.tail(3).to_string())
    ohlcv.to_parquet(OUT / 'ohlcv_sample.parquet')
    has_shares = any('좌수' in c or '순자산' in c or '시가총액' in c for c in ohlcv.columns)
    print(f'>> 상장좌수/순자산총액 컬럼 존재: {has_shares}  (자금흐름 직접계산 가능 여부)')

# 4) 괴리율 / 추적오차 (과거 시계열 — Phase1 백테스트 가능)
sec('4) 괴리율 / 추적오차 과거 시계열')
dev = call(f'get_etf_price_deviation', lambda: stock.get_etf_price_deviation(d0_60(BASE), BASE, sample_tk))
if dev is not None:
    print('괴리율 컬럼:', list(dev.columns)); print(dev.tail(3).to_string()); dev.to_parquet(OUT/'deviation_sample.parquet')
te = call('get_etf_tracking_error', lambda: stock.get_etf_tracking_error(d0_60(BASE), BASE, sample_tk))
if te is not None:
    print('추적오차 컬럼:', list(te.columns)); print(te.tail(3).to_string())

# 5) 구성종목 PDF — 핵심: 과거 날짜 서빙되나? 비중 컬럼 있나?
sec('5) 구성종목(PDF) — 과거 날짜 서빙 + 비중 컬럼 (★ 스마트머니 엔진 핵심)')
# 액티브 ETF 하나 찾기 (이름에 '액티브')
act_tk = None
# 이름 조회 (티커→이름) — 적은 수만
for tk in tickers[:80]:
    nm = call(f'name({tk})', lambda tk=tk: stock.get_etf_ticker_name(tk))
    if nm:
        names[tk] = nm
        if '액티브' in nm and act_tk is None:
            act_tk = tk
    if act_tk and len(names) > 20:
        break
json.dump(names, open(OUT/'etf_names_sample.json','w',encoding='utf-8'), ensure_ascii=False, indent=1)
print(f'\n액티브 ETF 예시 티커: {act_tk} ({names.get(act_tk)})')
probe_tk = act_tk or sample_tk
pdf_today = call(f'PDF({probe_tk}, {BASE})', lambda: stock.get_etf_portfolio_deposit_file(probe_tk, BASE))
if pdf_today is not None:
    print('PDF 컬럼:', list(pdf_today.columns)); print('보유종목수:', len(pdf_today))
    print(pdf_today.head(8).to_string()[:1500]); pdf_today.to_parquet(OUT/'pdf_today_sample.parquet')
# 과거 날짜 PDF 서빙 테스트 (30영업일 전)
past = (pd.Timestamp(BASE) - pd.Timedelta(days=40)).strftime('%Y%m%d')
past_bday = stock.get_nearest_business_day_in_a_week(past); time.sleep(SLEEP)
pdf_past = call(f'PDF 과거({probe_tk}, {past_bday})', lambda: stock.get_etf_portfolio_deposit_file(probe_tk, past_bday))
if pdf_past is not None and pdf_today is not None:
    print('>> 과거 PDF 서빙됨! 홀딩스 history 백필 가능')
    # diff 데모
    keycol = '티커' if '티커' in pdf_today.columns else pdf_today.columns[0]
    s_now = set(pdf_today[keycol].astype(str)); s_old = set(pdf_past[keycol].astype(str))
    print(f'  신규편입: {len(s_now - s_old)}종목, 편출: {len(s_old - s_now)}종목 (리밸런싱 detect 데모)')
    pdf_past.to_parquet(OUT/'pdf_past_sample.parquet')
else:
    print('>> 과거 PDF 미서빙 가능성 → 홀딩스는 forward 수집 필요')

sec('프로브 완료 — _probe_out/ 확인')
print('다음: 컬럼 확정되면 etf_flow_backtest.py 데이터로더를 실제 컬럼명에 맞춰 채움')
