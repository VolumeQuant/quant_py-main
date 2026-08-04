# -*- coding: utf-8 -*-
"""4계절 검증 — 2단계: 국면 라벨링 (실시간 vintage vs 사후 최종) + 지연 측정

규칙 (지시서 3.1):
  경기_상승 = PMI_3mma > 50
  물가_상승 = CPI_YoY 3개월 변화 > 0
  봄=상승&~물가 / 여름=상승&물가 / 가을=~상승&물가 / 겨울=~상승&~물가
  간절기 = PMI_3mma가 48~52 구간 (V1/V2 분기용 플래그)

실시간: 매월 말일 D 기준, 그 시점까지 발표된 값만 사용
  - PMI: release_date <= D 인 최초발표치 (investing.com, 발표일 실측)
  - CPI: ALFRED vintage as-of D (realtime_start <= D <= realtime_end)
사후: 최신 vintage(CPI) + 최초발표 PMI(리비전 미미 — 한계 문서화)

산출: output/regime_labels.csv, output/label_delays.csv
"""
import os
import numpy as np
import pandas as pd

np.random.seed(42)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "four_seasons", "cache")
OUT = os.path.join(ROOT, "output")

REGIMES = ["Spring", "Summer", "Autumn", "Winter"]


def load_data():
    cpi = pd.read_parquet(os.path.join(CACHE, "alfred_CPIAUCSL.parquet"))
    pmi = pd.read_parquet(os.path.join(CACHE, "pmi_releases.parquet"))
    return cpi, pmi


def cpi_asof(cpi, D):
    """ALFRED vintage as-of D → (obs월 index, CPI 값) 시리즈"""
    m = cpi[(cpi.realtime_start <= D) & (cpi.realtime_end >= D)]
    s = m.sort_values("realtime_start").groupby("date")["value"].last().sort_index()
    return s


def classify(pmi_3mma, cpi_mom_change, pmi_thresh=50.0):
    growth_up = pmi_3mma > pmi_thresh
    infl_up = cpi_mom_change > 0
    if growth_up and not infl_up:
        return "Spring"
    if growth_up and infl_up:
        return "Summer"
    if (not growth_up) and infl_up:
        return "Autumn"
    return "Winter"


def realtime_labels(cpi, pmi, months, pmi_thresh=50.0, cpi_window=3, band=2.0):
    """각 월말 D 시점의 실시간 라벨. months = 판정월(월초 타임스탬프) 리스트."""
    rows = []
    pmi_sorted = pmi.sort_values("release_date")
    for m in months:
        D = m + pd.offsets.MonthEnd(1)  # 판정월 말일
        pk = pmi_sorted[pmi_sorted.release_date <= D]
        if len(pk) < 3:
            continue
        p3 = pk.tail(3)["value"].mean()
        cs = cpi_asof(cpi, D)
        yoy = cs.pct_change(12)
        ch = yoy - yoy.shift(cpi_window)
        ch = ch.dropna()
        if ch.empty:
            continue
        rows.append(dict(month=m, decision_date=D,
                         pmi_3mma=p3, pmi_latest_month=pk.iloc[-1]["target_month"],
                         cpi_change=ch.iloc[-1], cpi_latest_month=ch.index[-1],
                         label=classify(p3, ch.iloc[-1], pmi_thresh),
                         interseason=abs(p3 - pmi_thresh) <= band))
    return pd.DataFrame(rows).set_index("month")


def final_labels(cpi, pmi, months, pmi_thresh=50.0, cpi_window=3, band=2.0):
    """사후(최종 수정치) 라벨: 관측월 M에 그 달 데이터까지 반영해 부여."""
    latest = cpi.sort_values("realtime_start").groupby("date")["value"].last().sort_index()
    yoy = latest.pct_change(12)
    ch = (yoy - yoy.shift(cpi_window)).dropna()
    p = pmi.set_index("target_month")["value"].sort_index()
    p3 = p.rolling(3).mean()
    rows = []
    for m in months:
        if m not in p3.index or pd.isna(p3.loc[m]) or m not in ch.index:
            continue
        rows.append(dict(month=m, pmi_3mma=p3.loc[m], cpi_change=ch.loc[m],
                         label=classify(p3.loc[m], ch.loc[m], pmi_thresh),
                         interseason=abs(p3.loc[m] - pmi_thresh) <= band))
    return pd.DataFrame(rows).set_index("month")


def measure_delays(rt, fin, trading_days):
    """사후 라벨 전환마다: 사후 기준 매매가능일 vs 실시간 감지 후 매매일의 차이(일)."""
    def first_td_after(month_begin):
        nxt = month_begin + pd.offsets.MonthBegin(1)
        cand = trading_days[trading_days >= nxt]
        return cand[0] if len(cand) else pd.NaT

    f = fin["label"]
    trans = f[f != f.shift(1)].iloc[1:]  # 첫 행 제외
    rows = []
    for m, reg in trans.items():
        hind_trade = first_td_after(m)
        # 실시간이 그 국면으로 처음 전환 감지한 판정월 (>= m)
        cand = rt[(rt.index >= m) & (rt["label"] == reg)]
        # 다음 사후 전환 이전까지만 탐색 (놓친 전환 판정)
        nxt_trans = trans.index[trans.index > m]
        limit = nxt_trans[0] if len(nxt_trans) else rt.index[-1] + pd.offsets.MonthBegin(1)
        cand = cand[cand.index < limit]
        if len(cand):
            det_m = cand.index[0]
            rt_trade = first_td_after(det_m)
            delay = (rt_trade - hind_trade).days if pd.notna(rt_trade) and pd.notna(hind_trade) else np.nan
            rows.append(dict(final_month=m, regime=reg, hindsight_trade=hind_trade,
                             detect_month=det_m, realtime_trade=rt_trade,
                             delay_days=delay, missed=False))
        else:
            rows.append(dict(final_month=m, regime=reg, hindsight_trade=hind_trade,
                             detect_month=pd.NaT, realtime_trade=pd.NaT,
                             delay_days=np.nan, missed=True))
    return pd.DataFrame(rows)


def main():
    cpi, pmi = load_data()
    px = pd.read_parquet(os.path.join(CACHE, "etf_daily.parquet"))
    trading_days = px.index

    months = pd.date_range("2006-11-01", "2026-06-01", freq="MS")
    rt = realtime_labels(cpi, pmi, months)
    fin = final_labels(cpi, pmi, months)

    delays = measure_delays(rt, fin, trading_days)

    merged = pd.DataFrame({
        "realtime_label": rt["label"], "realtime_interseason": rt["interseason"],
        "realtime_pmi_3mma": rt["pmi_3mma"], "realtime_cpi_change": rt["cpi_change"],
        "final_label": fin["label"], "final_interseason": fin["interseason"],
        "final_pmi_3mma": fin["pmi_3mma"], "final_cpi_change": fin["cpi_change"],
    })
    merged.to_csv(os.path.join(OUT, "regime_labels.csv"))
    delays.to_csv(os.path.join(OUT, "label_delays.csv"), index=False)

    print(f"realtime labels: {len(rt)} months {rt.index[0].date()}..{rt.index[-1].date()}")
    print(f"final labels   : {len(fin)} months {fin.index[0].date()}..{fin.index[-1].date()}")
    print("\n[realtime label counts]"); print(rt["label"].value_counts().to_string())
    print("interseason months (realtime):", int(rt["interseason"].sum()))
    print("\n[final label counts]"); print(fin["label"].value_counts().to_string())
    print("\n[final transitions]", len(delays), "| missed by realtime:", int(delays["missed"].sum()))
    ok = delays.dropna(subset=["delay_days"])
    if len(ok):
        print(f"delay days: median={ok.delay_days.median():.0f}, "
              f"IQR=[{ok.delay_days.quantile(.25):.0f},{ok.delay_days.quantile(.75):.0f}], "
              f"max={ok.delay_days.max():.0f}, n={len(ok)}")
    agree = (merged.dropna(subset=["realtime_label", "final_label"])
             .pipe(lambda d: (d.realtime_label == d.final_label).mean()))
    print(f"realtime vs final label agreement: {agree:.1%}")


if __name__ == "__main__":
    main()
