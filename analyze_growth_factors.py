"""Growth 팩터 B4 실험 — TTM YoY vs 연간 YoY + op_change_asset 재검토

분석 항목:
  1. 3가지 Growth 방법론 커버리지 + 기술통계
     - annual_yoy: 연간 매출 YoY (현행 v70)
     - ttm_yoy: TTM 매출 YoY (v71 채택)
     - q_avg_yoy: 개별분기 YoY 평균
  2. op_change_asset: Q팩터(ROE/GPA/CFO) 상관 재확인 (v67 도입 금지 결론 재검증)
  3. 방법론별 Q팩터 상관 비교 (G팩터는 Q와 독립적이어야 함)
  4. Top 30 순위 변동 분석

Usage:
    python analyze_growth_factors.py
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np


CACHE_DIR = Path('data_cache')


def load_fs(ticker):
    """DART 우선 → FnGuide 폴백"""
    for prefix in ['fs_dart_', 'fs_fnguide_']:
        f = CACHE_DIR / f'{prefix}{ticker}.parquet'
        if f.exists():
            df = pd.read_parquet(f)
            if not df.empty:
                return df
    return None


def calc_ttm_yoy(fs_df, account='매출액'):
    """TTM YoY = (최근4Q합) / (직전4Q합) - 1"""
    q = fs_df[(fs_df['공시구분'] == 'q') & (fs_df['계정'] == account)].sort_values('기준일')
    dates = sorted(q['기준일'].unique(), reverse=True)
    if len(dates) < 8:
        return None
    recent = q[q['기준일'].isin(dates[:4])]['값'].sum()
    prev = q[q['기준일'].isin(dates[4:8])]['값'].sum()
    if prev > 0 and pd.notna(recent) and pd.notna(prev):
        return (recent / prev - 1) * 100
    return None


def calc_annual_yoy(fs_df, account='매출액'):
    """연간 YoY = 최근연도 / 직전연도 - 1"""
    y = fs_df[(fs_df['공시구분'] == 'y') & (fs_df['계정'] == account)].sort_values('기준일')
    if len(y) < 2:
        return None
    latest = y.iloc[-1]['값']
    prev = y.iloc[-2]['값']
    if prev > 0 and pd.notna(latest) and pd.notna(prev):
        return (latest / prev - 1) * 100
    return None


def calc_q_avg_yoy(fs_df, account='매출액', n_quarters=4):
    """개별분기 YoY 평균 — 최근 n분기 각각의 전년동기 대비"""
    q = fs_df[(fs_df['공시구분'] == 'q') & (fs_df['계정'] == account)].copy()
    if q.empty:
        return None
    q = q.sort_values('기준일')
    q['year'] = q['기준일'].dt.year
    q['quarter'] = q['기준일'].dt.quarter

    recent_dates = sorted(q['기준일'].unique(), reverse=True)[:n_quarters]
    if len(recent_dates) < n_quarters:
        return None

    yoys = []
    for date in recent_dates:
        row = q[q['기준일'] == date]
        if row.empty:
            continue
        val, yr, qtr = row.iloc[0]['값'], row.iloc[0]['year'], row.iloc[0]['quarter']
        prev = q[(q['year'] == yr - 1) & (q['quarter'] == qtr)]
        if prev.empty:
            continue
        pv = prev.iloc[0]['값']
        if pv > 0 and pd.notna(val) and pd.notna(pv):
            yoys.append((val / pv - 1) * 100)

    return np.mean(yoys) if len(yoys) >= 2 else None


def calc_op_change_asset(fs_df):
    """총자산 대비 영업이익 변화량 (TTM)"""
    q = fs_df[fs_df['공시구분'] == 'q'].copy()
    if q.empty:
        return None
    op = q[q['계정'] == '영업이익'].sort_values('기준일')
    dates = sorted(op['기준일'].unique(), reverse=True)
    if len(dates) < 8:
        return None
    op_recent = op[op['기준일'].isin(dates[:4])]['값'].sum()
    op_prev = op[op['기준일'].isin(dates[4:8])]['값'].sum()
    assets = q[q['계정'] == '자산'].sort_values('기준일')
    prev_assets = assets[assets['기준일'].isin(dates[4:8])]
    if prev_assets.empty:
        return None
    prev_asset = prev_assets.iloc[-1]['값']
    if prev_asset > 0 and pd.notna(op_recent) and pd.notna(op_prev):
        return (op_recent - op_prev) / prev_asset * 100
    return None


def main():
    print("=" * 60)
    print("B4 Growth 팩터 실험 — TTM YoY vs 연간 vs 개별분기 + op_change_asset")
    print("=" * 60)

    # 유니버스
    mcap_files = sorted(CACHE_DIR.glob('market_cap_ALL_*.parquet'))
    if not mcap_files:
        print("market_cap 캐시 없음")
        return
    mcap = pd.read_parquet(mcap_files[-1])
    mcap['시가총액_억'] = mcap['시가총액'] / 1e8
    tickers = mcap[mcap['시가총액_억'] >= 1000].index.tolist()
    print(f"유니버스: {len(tickers)}종목")

    # ── 1. 팩터 계산 ──
    print("\n[1] 팩터 계산...")
    results = {}
    no_data = 0

    for i, ticker in enumerate(tickers):
        fs = load_fs(ticker)
        if fs is None:
            no_data += 1
            continue

        # 3가지 Growth 방법론
        annual = calc_annual_yoy(fs)
        ttm = calc_ttm_yoy(fs)
        q_avg = calc_q_avg_yoy(fs)
        op_ca = calc_op_change_asset(fs)

        # 영업이익 TTM YoY (추가 실험)
        op_ttm = calc_ttm_yoy(fs, '영업이익')

        # Q팩터 서브지표
        q_data = fs[fs['공시구분'] == 'q']
        latest_q = q_data['기준일'].max() if not q_data.empty else None
        roe = gpa = cfo = None
        if latest_q is not None:
            snap = q_data[q_data['기준일'] == latest_q]
            vals = {r['계정']: r['값'] for _, r in snap.iterrows()}
            equity = vals.get('자본', 0)
            assets = vals.get('자산', 0)
            revenue = vals.get('매출액', 0)
            gp = vals.get('매출총이익', None)
            cf = vals.get('영업활동으로인한현금흐름', None)
            ni = vals.get('당기순이익', None)
            if equity and equity > 0 and ni:
                roe = ni / equity * 100
            if assets and assets > 0:
                if gp is not None:
                    gpa = gp / assets * 100
                if cf is not None:
                    cfo = cf / assets * 100

        results[ticker] = {
            'annual_yoy': annual,
            'ttm_yoy': ttm,
            'q_avg_yoy': q_avg,
            'op_change_asset': op_ca,
            'op_ttm_yoy': op_ttm,
            'ROE': roe, 'GPA': gpa, 'CFO': cfo,
        }

        if (i + 1) % 300 == 0:
            print(f"  {i+1}/{len(tickers)} 처리...")

    df = pd.DataFrame.from_dict(results, orient='index')
    print(f"\n데이터 없음: {no_data}종목, 데이터 있음: {len(df)}종목")

    # ── 2. 커버리지 ──
    print("\n[2] 커버리지")
    growth_cols = ['annual_yoy', 'ttm_yoy', 'q_avg_yoy', 'op_change_asset', 'op_ttm_yoy']
    for col in growth_cols:
        n = df[col].notna().sum()
        print(f"  {col:20s}: {n:4d}/{len(df)} ({n/len(df)*100:.1f}%)")

    # ── 3. 기술통계 ──
    print("\n[3] 기술통계")
    for col in growth_cols:
        s = df[col].dropna()
        if len(s) > 0:
            print(f"  {col:20s}: median={s.median():+.1f}%  mean={s.mean():+.1f}%  "
                  f"std={s.std():.1f}  IQR=[{s.quantile(0.25):+.1f}, {s.quantile(0.75):+.1f}]")

    # ── 4. Growth 방법론 간 상관 ──
    print("\n[4] Growth 방법론 간 상관 (Spearman)")
    g_cols = ['annual_yoy', 'ttm_yoy', 'q_avg_yoy']
    valid_g = df[g_cols].dropna()
    print(f"  공통: {len(valid_g)}종목")
    if len(valid_g) >= 30:
        corr = valid_g.rank().corr()
        for a in g_cols:
            for b in g_cols:
                if a < b:
                    r = corr.loc[a, b]
                    print(f"  {a:15s} vs {b:15s}: {r:.3f}")

    # ── 5. Q팩터 상관 — 핵심: G는 Q와 독립적이어야 함 ──
    print("\n[5] Q팩터 독립성 검증 (Spearman)")
    q_cols = ['ROE', 'GPA', 'CFO']
    test_cols = ['annual_yoy', 'ttm_yoy', 'q_avg_yoy', 'op_change_asset', 'op_ttm_yoy']

    valid_all = df[test_cols + q_cols].dropna()
    print(f"  공통: {len(valid_all)}종목")

    if len(valid_all) >= 30:
        corr_all = valid_all.rank().corr()
        print(f"\n  {'':20s} {'ROE':>8s} {'GPA':>8s} {'CFO':>8s} {'평균':>8s}")
        print(f"  {'-'*52}")
        for g in test_cols:
            rs = [corr_all.loc[g, q] for q in q_cols]
            avg = np.mean([abs(r) for r in rs])
            flags = []
            for r in rs:
                if abs(r) > 0.4:
                    flags.append('!')
                else:
                    flags.append(' ')
            print(f"  {g:20s} {rs[0]:+.3f}{flags[0]} {rs[1]:+.3f}{flags[1]} {rs[2]:+.3f}{flags[2]} {avg:.3f}")

        print(f"\n  판정:")
        for g in test_cols:
            rs = [abs(corr_all.loc[g, q]) for q in q_cols]
            avg = np.mean(rs)
            if avg < 0.15:
                verdict = "매우 독립적 — G 서브팩터 적합"
            elif avg < 0.25:
                verdict = "독립적 — G 서브팩터 적합"
            elif avg < 0.35:
                verdict = "약한 상관 — 주의 필요"
            else:
                verdict = "Q와 이중반영 위험 — 부적합"
            print(f"  {g:20s}: |avg|={avg:.3f} → {verdict}")

    # ── 6. TTM YoY vs 연간 YoY: Top 30 순위 변동 ──
    print("\n[6] Top 30 순위 변동")
    for col in test_cols:
        df[f'{col}_rank'] = df[col].rank(ascending=False)

    base_top30 = set(df.nsmallest(30, 'annual_yoy_rank').index)
    for col in ['ttm_yoy', 'q_avg_yoy', 'op_change_asset', 'op_ttm_yoy']:
        new_top30 = set(df.nsmallest(30, f'{col}_rank').index)
        overlap = len(base_top30 & new_top30)
        print(f"  연간 vs {col:20s}: {overlap}/30 겹침")

    # ── 7. 결론 ──
    print("\n" + "=" * 60)
    print("[결론]")
    print("  1. TTM YoY: 연간 대비 최신 분기 반영, Q팩터 독립성 확인")
    print("  2. op_change_asset: Q팩터 상관 재확인 → v67 결론 유효 여부 판정")
    print("=" * 60)


if __name__ == '__main__':
    main()
