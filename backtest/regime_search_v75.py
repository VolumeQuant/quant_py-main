"""v75 국면전환 전면 서치 — 단독 전략 Top 30 기반

Phase 3: 국면 규칙 × 방어/공격 조합 전면 테스트
  - 지수 추세 (KOSPI/KOSDAQ MA20/60/120/200)
  - 브레스 (MA120 위 종목 비율 30/40/50/60%)
  - VIX (<20, <25, <30)
  - HY Spread (<4, <5, <6%)
  - 확인 일수 (1, 3, 5, 7)
  - 결합 규칙

Usage:
    python backtest/regime_search_v75.py
"""
import sys, os, json, time
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
PROJECT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np

CACHE_DIR = PROJECT / 'data_cache'
BT_DIR = PROJECT / 'backtest' / 'bt_v75'
RESULTS_DIR = PROJECT / 'backtest_results'


# ============================================================================
# 시장 데이터 로드
# ============================================================================
def load_market_data():
    """지수, VIX, HY 데이터 로드"""
    kospi = pd.read_parquet(CACHE_DIR / 'kospi_yf.parquet').iloc[:, 0]
    kosdaq = pd.read_parquet(CACHE_DIR / 'kosdaq_yf.parquet').iloc[:, 0]

    vix = None
    if (CACHE_DIR / 'vix_daily.parquet').exists():
        vix = pd.read_parquet(CACHE_DIR / 'vix_daily.parquet').iloc[:, 0]

    hy = None
    if (CACHE_DIR / 'hy_spread.parquet').exists():
        hy = pd.read_parquet(CACHE_DIR / 'hy_spread.parquet').iloc[:, 0]

    return kospi, kosdaq, vix, hy


def compute_breadth(ohlcv):
    """전종목 MA120 위 비율"""
    ma120 = ohlcv.rolling(120).mean()
    above = (ohlcv > ma120).sum(axis=1)
    total = ohlcv.notna().sum(axis=1)
    return above / total


# ============================================================================
# 국면 규칙 생성
# ============================================================================
def make_regime_signals(dates, kospi, kosdaq, vix, hy, breadth):
    """모든 국면 규칙의 일별 신호 생성 (True=공격, False=방어)"""

    def get_val(series, dt, lag=1):
        """lag=1: 전일 데이터 사용 (look-ahead 방지)"""
        if series is None:
            return None
        # dt 이전 데이터만 사용
        prev = series[series.index < dt] if lag > 0 else series[series.index <= dt]
        if prev.empty:
            return None
        v = prev.iloc[-1]
        return v if v is not None and not pd.isna(v) else None

    # MA 계산 (get_val에서 lag=1로 전일 사용하므로, MA 자체는 당일 포함해도 OK)
    ma_cache = {}
    for name, series in [('kospi', kospi), ('kosdaq', kosdaq)]:
        for period in [20, 60, 120, 200]:
            ma_cache[f'{name}_ma{period}'] = series.rolling(period).mean()

    rules = {}

    # 1. 단일 지수 MA
    for idx_name, idx_series in [('KP', kospi), ('KQ', kosdaq)]:
        for ma_p in [20, 60, 120, 200]:
            ma = ma_cache[f'{idx_name.lower().replace("kp","kospi").replace("kq","kosdaq")}_ma{ma_p}']
            rule_name = f'{idx_name}_MA{ma_p}'
            signal = {}
            for d in dates:
                dt = pd.Timestamp(d)
                k = get_val(idx_series, dt)
                m = get_val(ma, dt)
                signal[d] = bool(k is not None and m is not None and k > m)
            rules[rule_name] = signal

    # 2. KOSPI AND KOSDAQ
    for ma_p in [20, 60, 120, 200]:
        rule_name = f'KK_MA{ma_p}'
        signal = {}
        for d in dates:
            kp = rules[f'KP_MA{ma_p}'].get(d, False)
            kq = rules[f'KQ_MA{ma_p}'].get(d, False)
            signal[d] = kp and kq
        rules[rule_name] = signal

    # 3. 브레스
    for thresh in [0.30, 0.40, 0.50, 0.60]:
        rule_name = f'Breadth{int(thresh*100)}'
        signal = {}
        for d in dates:
            dt = pd.Timestamp(d)
            b = get_val(breadth, dt)
            signal[d] = bool(b is not None and b > thresh)
        rules[rule_name] = signal

    # 4. VIX
    if vix is not None:
        for thresh in [20, 25, 30]:
            rule_name = f'VIX_lt{thresh}'
            signal = {}
            for d in dates:
                dt = pd.Timestamp(d)
                v = get_val(vix, dt)
                signal[d] = bool(v is not None and v < thresh)
            rules[rule_name] = signal

    # 5. HY Spread
    if hy is not None:
        for thresh in [4.0, 5.0, 6.0]:
            rule_name = f'HY_lt{thresh}'
            signal = {}
            for d in dates:
                dt = pd.Timestamp(d)
                h = get_val(hy, dt)
                signal[d] = bool(h is not None and h < thresh)
            rules[rule_name] = signal

    # 6. 결합 규칙
    combo_pairs = [
        ('KK_MA60', 'Breadth50'),
        ('KK_MA60', 'VIX_lt25'),
        ('KK_MA60', 'HY_lt5.0'),
        ('KP_MA60', 'Breadth50'),
        ('KP_MA120', 'VIX_lt25'),
    ]
    for r1, r2 in combo_pairs:
        if r1 in rules and r2 in rules:
            rule_name = f'{r1}+{r2}'
            signal = {}
            for d in dates:
                signal[d] = rules[r1].get(d, False) and rules[r2].get(d, False)
            rules[rule_name] = signal

    return rules


def apply_confirmation(signal, dates, confirm_days):
    """확인 일수 적용: N일 연속 신호 유지해야 전환"""
    regime = {}
    streak = 0
    current = False
    prev = None
    for d in dates:
        s = signal.get(d, False)
        if s == prev:
            streak += 1
        else:
            streak = 1
        prev = s
        if streak >= confirm_days:
            current = s
        regime[d] = current
    return regime


# ============================================================================
# 성과 계산
# ============================================================================
def calc_stats(rets):
    arr = np.array(rets)
    n = len(arr)
    if n == 0 or arr.std() == 0:
        return 0, 0, 0, 0, 0
    cum = np.cumprod(1 + arr)
    y = n / 252
    cagr = (cum[-1] ** (1/y) - 1) * 100
    peak = np.maximum.accumulate(np.concatenate([[1.0], cum]))
    dd = (np.concatenate([[1.0], cum]) - peak) / peak
    mdd = abs(dd.min()) * 100
    calmar = cagr / mdd if mdd > 0 else 0
    sharpe = arr.mean() / arr.std() * np.sqrt(252)
    neg = arr[arr < 0]
    sortino = arr.mean() / neg.std() * np.sqrt(252) if len(neg) > 0 and neg.std() > 0 else sharpe
    return cagr, mdd, calmar, sharpe, sortino


# ============================================================================
# Main
# ============================================================================
def main():
    t_start = time.time()
    print('=== v75 국면전환 서치 ===')

    # 데이터 로드
    from grid_search_v75 import load_bt_rankings, load_prices
    from turbo_simulator import TurboSimulator

    all_rankings, dates = load_bt_rankings(BT_DIR)
    prices = load_prices()
    bench = pd.read_parquet(CACHE_DIR / 'bench_proxy.parquet') \
        if (CACHE_DIR / 'bench_proxy.parquet').exists() else pd.DataFrame()

    print(f'거래일: {len(dates)} ({dates[0]}~{dates[-1]})')

    kospi, kosdaq, vix, hy = load_market_data()
    breadth = compute_breadth(prices)

    # 국면 규칙 생성
    raw_signals = make_regime_signals(dates, kospi, kosdaq, vix, hy, breadth)
    print(f'국면 규칙: {len(raw_signals)}개')

    # 확인 일수 적용
    confirm_days_list = [1, 3, 5, 7]
    all_regimes = {}
    for rule_name, signal in raw_signals.items():
        for cd in confirm_days_list:
            regime = apply_confirmation(signal, dates, cd)
            all_regimes[f'{rule_name}_{cd}d'] = regime

    print(f'확인일수 포함 국면: {len(all_regimes)}개')

    # 단독 전략 결과 로드 (final + 2a 광범위 후보)
    singles_path = RESULTS_DIR / 'v75_final_singles.csv'
    phase2a_path = RESULTS_DIR / 'phase2a_screening.csv'
    if not singles_path.exists():
        print('v75_final_singles.csv 없음 — 먼저 grid_search_v75.py 실행')
        return

    finals = pd.read_csv(singles_path)
    # Phase 2a에서 다양한 후보 추가 (final에 없는 공격적/방어적 전략)
    if phase2a_path.exists():
        phase2a = pd.read_csv(phase2a_path)
        # Phase 2a Top 100 중 final에 없는 것 추가
        extra = phase2a.head(100).merge(
            finals[['v','q','g','m','g_rev','mom']], how='left', indicator=True
        ).query('_merge == "left_only"').drop(columns='_merge').head(30)
        # extra에 entry/exit/slots 등 기본값 설정
        for col, val in [('entry', 5), ('exit', 12), ('slots', 5),
                         ('sl', -0.10), ('trail', None), ('corr', None)]:
            if col not in extra.columns:
                extra[col] = val
        singles = pd.concat([finals, extra], ignore_index=True)
        print(f'후보 확장: final {len(finals)} + extra {len(extra)} = {len(singles)}')
    else:
        singles = finals
    print(f'단독 전략: {len(singles)}개')

    # 각 단독 전략의 daily_rets 생성
    tsim = TurboSimulator(all_rankings, dates, prices, bench)
    strat_rets = {}

    for idx, cfg in singles.iterrows():
        r = tsim.run_fast(
            cfg.v/100, cfg.q/100, cfg.g/100, cfg.m/100, cfg.g_rev,
            entry_param=int(cfg.entry), exit_param=cfg['exit'],
            max_slots=int(cfg.slots),
            stop_loss=cfg.sl if pd.notna(cfg.sl) else None,
            corr_threshold=cfg.corr_th if pd.notna(cfg.corr_th) else None,
            trailing_stop=cfg.trail if pd.notna(cfg.trail) else None,
            mom_type=cfg.mom
        )
        strat_rets[idx] = r['_daily_rets']

    print(f'전략별 daily_rets 생성 완료: {len(strat_rets)}개')

    # 단독 최고 Calmar
    best_single_calmar = singles.iloc[0]['calmar'] if not singles.empty else 0
    print(f'단독 최고 Calmar: {best_single_calmar:.2f}')

    # ================================================================
    # Stage 1: 빠른 스크리닝 (daily_rets 조합 — 근사치)
    # ================================================================
    print(f'\n{"="*80}')
    print(f'Stage 1: 국면전환 빠른 스크리닝 (daily_rets 조합)')
    print(f'  방어: {len(singles)}개 × 공격: {len(singles)}개 × 규칙: {len(all_regimes)}개')
    total = len(singles) * (len(singles)-1) * len(all_regimes)
    print(f'  총: {total:,}개')
    print(f'{"="*80}', flush=True)

    approx_results = []
    done = 0
    t0 = time.time()

    for d_idx, d_cfg in singles.iterrows():
        for o_idx, o_cfg in singles.iterrows():
            if d_idx == o_idx:
                continue
            d_rets = strat_rets[d_idx]
            o_rets = strat_rets[o_idx]

            for rule_name, regime in all_regimes.items():
                combined = [
                    o_rets[i] if regime.get(d, False) else d_rets[i]
                    for i, d in enumerate(dates)
                ]
                cagr, mdd, calmar, sharpe, sortino = calc_stats(combined)

                if calmar > best_single_calmar * 0.8:
                    boost_pct = sum(1 for v in regime.values() if v) / len(regime) * 100
                    approx_results.append({
                        'defense': d_idx, 'offense': o_idx,
                        'rule': rule_name, 'boost_pct': boost_pct,
                        'cagr': cagr, 'mdd': mdd, 'calmar': calmar,
                        'sharpe': sharpe, 'sortino': sortino,
                    })

            done += len(all_regimes)
            if done % 200000 == 0:
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed > 0 else 1
                remain = (total - done) / rate
                print(f'  [{done:,}/{total:,}] {elapsed:.0f}초 | 남은 ~{remain:.0f}초', flush=True)

    approx_df = pd.DataFrame(approx_results)
    if approx_df.empty:
        print('국면전환이 단독보다 나은 조합 없음')
        return
    approx_df = approx_df.sort_values('calmar', ascending=False)
    print(f'  Stage 1 완료: {len(approx_df)}개 후보 (근사치)', flush=True)

    # ================================================================
    # Stage 2: 정확한 시뮬레이션 (run_regime — 전환 시 청산+재진입)
    # ================================================================
    n_verify = min(200, len(approx_df))
    print(f'\n{"="*80}')
    print(f'Stage 2: 정확한 국면전환 시뮬레이션 (Top {n_verify})')
    print(f'  전환 시 포트폴리오 청산 → 새 전략 3일검증 재진입')
    print(f'{"="*80}', flush=True)

    exact_results = []
    t0 = time.time()

    for rank, (_, row) in enumerate(approx_df.head(n_verify).iterrows()):
        d_cfg = singles.iloc[int(row.defense)]
        o_cfg = singles.iloc[int(row.offense)]
        rule_name = row.rule
        regime = all_regimes[rule_name]

        d_sl = d_cfg.sl if pd.notna(d_cfg.sl) else None
        d_ct = d_cfg.corr_th if pd.notna(d_cfg.corr_th) else None
        d_tr = d_cfg.trail if pd.notna(d_cfg.trail) else None
        o_sl = o_cfg.sl if pd.notna(o_cfg.sl) else None

        defense_params = {
            'v': d_cfg.v/100, 'q': d_cfg.q/100, 'g': d_cfg.g/100, 'm': d_cfg.m/100,
            'g_rev': d_cfg.g_rev, 'mom': d_cfg.mom,
            'entry': int(d_cfg.entry), 'exit': d_cfg['exit'], 'slots': int(d_cfg.slots),
        }
        offense_params = {
            'v': o_cfg.v/100, 'q': o_cfg.q/100, 'g': o_cfg.g/100, 'm': o_cfg.m/100,
            'g_rev': o_cfg.g_rev, 'mom': o_cfg.mom,
            'entry': int(o_cfg.entry), 'exit': o_cfg['exit'], 'slots': int(o_cfg.slots),
        }

        r = tsim.run_regime(
            defense_params, offense_params, regime,
            stop_loss=d_sl, corr_threshold=d_ct, trailing_stop=d_tr
        )

        exact_results.append({
            'defense': int(row.defense), 'offense': int(row.offense),
            'rule': rule_name, 'boost_pct': row.boost_pct,
            'approx_calmar': row.calmar,
            'calmar': r['calmar'], 'cagr': r['cagr'],
            'mdd': r['mdd'], 'sharpe': r['sharpe'], 'sortino': r['sortino'],
        })

        if (rank + 1) % 20 == 0:
            elapsed = time.time() - t0
            print(f'  [{rank+1}/{n_verify}] {elapsed:.0f}초', flush=True)

    exact_df = pd.DataFrame(exact_results)
    exact_df = exact_df.sort_values('calmar', ascending=False)
    exact_df.to_csv(RESULTS_DIR / 'v75_regime_results.csv', index=False)

    print(f'\n  근사치 vs 정확값 차이:')
    if not exact_df.empty:
        diff = (exact_df['calmar'] - exact_df['approx_calmar']).abs()
        print(f'    평균 |차이|: {diff.mean():.3f}, 최대: {diff.max():.3f}')

    print(f'\n국면전환 Top 10 (정확값):')
    for _, row in exact_df.head(10).iterrows():
        d_cfg = singles.iloc[int(row.defense)]
        o_cfg = singles.iloc[int(row.offense)]
        print(f'  방어=V{d_cfg.v}Q{d_cfg.q}G{d_cfg.g}M{d_cfg.m}'
              f' 공격=V{o_cfg.v}Q{o_cfg.q}G{o_cfg.g}M{o_cfg.m}'
              f' rule={row.rule} boost={row.boost_pct:.0f}%'
              f' | Cal={row.calmar:.2f}(근사{row.approx_calmar:.2f})'
              f' CAGR={row.cagr:.1f}% MDD={row.mdd:.1f}%')

    # 단독 vs 국면전환 비교
    print(f'\n{"="*80}')
    print(f'단독 vs 국면전환 비교')
    print(f'{"="*80}')
    print(f'  단독 1위: Calmar={best_single_calmar:.2f}')
    if not exact_df.empty:
        best_regime = exact_df.iloc[0]
        print(f'  국면전환 1위: Calmar={best_regime.calmar:.2f} (정확값)')
        if best_regime.calmar > best_single_calmar:
            print(f'  → 국면전환 우위 (+{best_regime.calmar - best_single_calmar:.2f})')
        else:
            print(f'  → 단독 전략 우위')

    elapsed = time.time() - t_start
    print(f'\n총 소요: {elapsed/60:.1f}분')


if __name__ == '__main__':
    main()
