"""ETF Phase 1 백테스트 스캐폴드 (회사 PC — pykrx 라이브 필요).

확인된 컬럼(NAV·종가·거래량·거래대금)만으로 즉시 검정 가능한 신호:
  - vol_surge: 거래대금 20일 대비 배수 (수급 급증 proxy)
  - nav_mom:   NAV 60일 모멘텀 (가격 아닌 NAV → 추적오차 노이즈 제거)
순자산총액/상장좌수가 프로브에서 확인되면 flow_z를 build_signals에 추가(아래 TODO).

규율: 주식 시스템과 동일 — IS/OOS, 워크포워드, 벤치(KODEX200) 대비, 비용 반영, PIT(T+1 진입).
데이터는 1회 수집 후 parquet 캐시 (pykrx 순차+1초).

실행:
  python etf_research/etf_flow_backtest.py --collect   # 최초 1회 데이터 수집
  python etf_research/etf_flow_backtest.py              # 백테스트
"""
import sys, time, argparse
from pathlib import Path
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).parent
CACHE = ROOT / '_bt_cache'; CACHE.mkdir(exist_ok=True)
SLEEP = 1.0
START, END = '20200101', None   # END=None → 최근 영업일
BENCH = '069500'  # KODEX 200
MAX_ETF = 200     # 수집 종목 상한 (유동성 상위) — 수집시간 관리
LEV_KW = ['레버리지', '인버스', '2X', '2x', '채권', '단기', '머니마켓', 'MMF', '국채', '통안']


def collect():
    # KRX 로그인 필수 (2026-02-27~). 빈응답=IP차단 아님, login 누락.
    sys.path.insert(0, str(ROOT.parent))
    import krx_auth
    if not krx_auth.login():
        print('[중단] KRX 로그인 실패 — config.py KRX_USER_ID/PASSWORD 확인'); sys.exit(1)
    import pykrx.stock as stock
    end = END or stock.get_nearest_business_day_in_a_week()
    print(f'수집 구간 {START}~{end}', flush=True)
    tickers = stock.get_etf_ticker_list(end); time.sleep(SLEEP)
    # 유동성 상위 선별 (전 종목 거래대금 1콜)
    d0 = (pd.Timestamp(end) - pd.Timedelta(days=20)).strftime('%Y%m%d')
    chg = stock.get_etf_price_change_by_ticker(d0, end); time.sleep(SLEEP)
    valcol = next((c for c in chg.columns if '거래대금' in c), None)
    if valcol:
        liquid = chg.sort_values(valcol, ascending=False).head(MAX_ETF).index.astype(str).tolist()
    else:
        liquid = tickers[:MAX_ETF]
    if BENCH not in liquid: liquid.append(BENCH)
    print(f'수집 대상 {len(liquid)} ETF (유동성 상위)', flush=True)
    names = {}
    closes, navs, vals = {}, {}, {}
    for i, tk in enumerate(liquid):
        try:
            df = stock.get_etf_ohlcv_by_date(START, end, tk)
            if df is not None and len(df):
                closes[tk] = df['종가']; navs[tk] = df['NAV'] if 'NAV' in df else df['종가']
                vc = next((c for c in df.columns if '거래대금' in c), None)
                if vc: vals[tk] = df[vc]
            names[tk] = stock.get_etf_ticker_name(tk)
        except Exception as e:
            print(f'  [skip] {tk}: {str(e)[:60]}', flush=True)
        if i % 20 == 0: print(f'  {i}/{len(liquid)}', flush=True)
        time.sleep(SLEEP)
    pd.DataFrame(closes).to_parquet(CACHE/'close.parquet')
    pd.DataFrame(navs).to_parquet(CACHE/'nav.parquet')
    pd.DataFrame(vals).to_parquet(CACHE/'value.parquet')
    pd.Series(names).to_json(CACHE/'names.json', force_ascii=False)
    print('수집 완료 → _bt_cache/', flush=True)


def build_signals(close, nav, value):
    """단일 변수씩. 반환: dict[name] = DataFrame(date×ticker) 신호값(높을수록 매수)."""
    sig = {}
    # 거래대금 급증
    v = value.rolling(20).mean()
    sig['vol_surge'] = value / v.replace(0, np.nan)
    # NAV 60일 모멘텀
    sig['nav_mom'] = nav / nav.shift(60) - 1
    # TODO(프로브 후): flow_z = (Δ순자산총액 − navret×AUM_prev) / AUM, z-score
    return sig


def run_bt(close, signal, k=5, rebal=5, cost=0.003, bench=None):
    """주기 rebal일마다 신호 상위 k ETF 동일비중. PIT: 신호는 T, 진입 T+1 종가(shift)."""
    rets = close.pct_change()
    sig = signal.shift(1)  # 룩어헤드 방지
    dates = close.index
    weights = pd.DataFrame(0.0, index=dates, columns=close.columns)
    held = []
    for i, d in enumerate(dates):
        if i % rebal == 0:
            row = sig.loc[d].dropna()
            # 유니버스: 가격 있고 신호 있는 것
            row = row[close.loc[d].notna()]
            held = row.sort_values(ascending=False).head(k).index.tolist()
        if held:
            weights.loc[d, held] = 1.0/len(held)
    # 비용: 보유 변경분에 cost
    turn = weights.diff().abs().sum(axis=1).fillna(0)
    port = (weights.shift(1) * rets).sum(axis=1) - turn*cost
    eq = (1+port).cumprod()
    return eq, _stats(eq)


def _stats(eq):
    eq = eq.dropna()
    if len(eq) < 50: return {}
    cagr = eq.iloc[-1]**(252/len(eq)) - 1
    pk = eq.cummax(); mdd = -((eq-pk)/pk).min()
    cal = cagr/mdd if mdd > 0 else 0
    sharpe = (eq.pct_change().mean()/eq.pct_change().std()*np.sqrt(252)) if eq.pct_change().std()>0 else 0
    return {'CAGR': cagr*100, 'MDD': mdd*100, 'Calmar': cal, 'Sharpe': sharpe, 'NAV': eq.iloc[-1]}


def main():
    close = pd.read_parquet(CACHE/'close.parquet')
    nav = pd.read_parquet(CACHE/'nav.parquet')
    value = pd.read_parquet(CACHE/'value.parquet')
    close.index = pd.to_datetime(close.index); nav.index = pd.to_datetime(nav.index); value.index = pd.to_datetime(value.index)
    sigs = build_signals(close, nav, value)
    # 벤치
    bench_eq = (1+close[BENCH].pct_change()).cumprod() if BENCH in close else None
    bstat = _stats(bench_eq) if bench_eq is not None else {}
    print(f"\n벤치(KODEX200): Cal {bstat.get('Calmar',0):.2f} CAGR {bstat.get('CAGR',0):.1f}% MDD {bstat.get('MDD',0):.1f}%")
    is_end = close.index[len(close)//2]
    print(f"\n{'신호':<12}{'구간':<6}{'Cal':>7}{'CAGR':>8}{'MDD':>7}{'Sharpe':>8}")
    for name, sg in sigs.items():
        for lbl, sub_c, sub_s in [('ALL', close, sg),
                                   ('IS', close[close.index<=is_end], sg[sg.index<=is_end]),
                                   ('OOS', close[close.index>is_end], sg[sg.index>is_end])]:
            eq, st = run_bt(sub_c, sub_s)
            if st:
                print(f"{name:<12}{lbl:<6}{st['Calmar']:>7.2f}{st['CAGR']:>7.1f}%{st['MDD']:>6.1f}%{st['Sharpe']:>8.2f}", flush=True)
        print()
    print('판정: OOS Cal이 벤치 초과 + IS/OOS 둘 다 양(+) 이어야 진짜 신호. 아니면 v1처럼 폐기.')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--collect', action='store_true')
    a = ap.parse_args()
    if a.collect: collect()
    else: main()
