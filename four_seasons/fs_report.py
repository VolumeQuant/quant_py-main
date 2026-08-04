# -*- coding: utf-8 -*-
"""4계절 검증 — 4단계: 보고서 + 차트 (metrics_summary.md, robustness.md, PNG 3종)"""
import os, sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

np.random.seed(42)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "four_seasons", "cache")
OUT = os.path.join(ROOT, "output")
sys.path.insert(0, os.path.join(ROOT, "four_seasons"))
from fs_labels import load_data, realtime_labels, final_labels, measure_delays
from fs_backtest import (load_prices, rebalance_returns, effective_labels,
                         portfolio_returns, metrics, ASSETS, REGIME_W)

# ---- dataviz 팔레트 (검증 통과) ----
INK = "#0b0b0b"; MUT = "#898781"; GRID = "#e1e0d9"; SURF = "#fcfcfb"
CAT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
REG_C = {"Spring": "#1baf7a", "Summer": "#eb6834", "Autumn": "#eda100", "Winter": "#2a78d6"}
REG_KR = {"Spring": "봄", "Summer": "여름", "Autumn": "가을", "Winter": "겨울"}

plt.rcParams.update({
    "font.family": "Malgun Gothic", "axes.unicode_minus": False,
    "figure.facecolor": SURF, "axes.facecolor": SURF,
    "axes.edgecolor": "#c3c2b7", "axes.labelcolor": MUT,
    "xtick.color": MUT, "ytick.color": MUT,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.7,
    "axes.spines.top": False, "axes.spines.right": False,
    "font.size": 10,
})


def fmt_pct(x, d=1):
    return f"{x * 100:.{d}f}%"


def main():
    df = pd.read_csv(os.path.join(OUT, "backtest_results.csv"), index_col=0, parse_dates=True)
    sens = pd.read_csv(os.path.join(OUT, "sensitivity_surface.csv"))
    durs = pd.read_csv(os.path.join(OUT, "regime_durations.csv"))
    delays = pd.read_csv(os.path.join(OUT, "label_delays.csv"), parse_dates=["final_month", "hindsight_trade", "realtime_trade"])
    sh_v1 = pd.read_csv(os.path.join(OUT, "shuffle_dist_V1.csv"))
    sh_v2 = pd.read_csv(os.path.join(OUT, "shuffle_dist_V2.csv"))
    labels = pd.read_csv(os.path.join(OUT, "regime_labels.csv"), index_col=0, parse_dates=True)

    cpi, pmi = load_data()
    px = load_prices()
    rets, _ = rebalance_returns(px)
    months = pd.date_range("2006-11-01", "2026-06-01", freq="MS")
    fin = final_labels(cpi, pmi, months)

    # ---------- H-A: 국면×자산 수익 매트릭스 ----------
    ha = {}
    for lagname, lag in [("t", 0), ("t1", 1)]:
        lab = fin["label"].copy(); lab.index = lab.index + pd.offsets.MonthBegin(lag)
        common = lab.index.intersection(rets.index)
        d = rets.loc[common, ASSETS]; d = d[d.index >= "2007-01-01"]
        g = d.groupby(lab.loc[d.index]).mean() * 12
        g["n"] = d.groupby(lab.loc[d.index]).size()
        ha[lagname] = g

    tbl = pd.DataFrame({k: metrics(df[k]) for k in df.columns}).T

    pct_v1 = (sh_v1.CAGR < metrics(df["V1"])["CAGR"]).mean() * 100
    pct_v1_s = (sh_v1.Sharpe < metrics(df["V1"])["Sharpe"]).mean() * 100
    pct_v2 = (sh_v2.CAGR < metrics(df["V2"])["CAGR"]).mean() * 100
    pct_v2_s = (sh_v2.Sharpe < metrics(df["V2"])["Sharpe"]).mean() * 100

    ok = delays.dropna(subset=["delay_days"])
    n_miss = int(delays["missed"].sum())

    # ---------- 차트 1: 누적수익 (로그) ----------
    fig, ax = plt.subplots(figsize=(10.5, 6))
    series = [("V1", "V1 실시간 (간절기=유지)"), ("V2", "V2 실시간 (간절기=현금)"),
              ("C4_final_V1", "C4 사후 라벨 (V1 방식)"), ("C1_SPY", "C1 SPY 매수보유"),
              ("C2_6040", "C2 60/40 분기리밸"), ("C5_EW6", "C5 6자산 동일비중")]
    for (k, nm), c in zip(series, CAT):
        eq = (1 + df[k].fillna(0)).cumprod()
        ax.plot(eq.index, eq.values, color=c, lw=1.8, label=nm)
        ax.annotate(f" {eq.iloc[-1]:.2f}x", xy=(eq.index[-1], eq.iloc[-1]),
                    color=c, fontsize=8.5, va="center")
    ax.set_yscale("log")
    ax.set_yticks([0.5, 1, 2, 4, 8]); ax.set_yticklabels(["0.5x", "1x", "2x", "4x", "8x"])
    ax.set_title("4계절 로테이션 vs 대조군 — 누적수익 (2007-01~2026-07, 비용 왕복 10bp, 로그)",
                 color=INK, fontsize=11, loc="left")
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "equity_curves.png"), dpi=150)
    plt.close(fig)

    # ---------- 차트 2: 국면 타임라인 + SPY ----------
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10.5, 6), sharex=True,
                                   gridspec_kw={"height_ratios": [4, 0.7], "hspace": 0.08})
    spy = px["SPY"].loc["2007-01-01":]

    def draw_bands(ax, lab_series):
        s = lab_series.dropna()
        prev, start = None, None
        for m, v in s.items():
            if v != prev:
                if prev is not None:
                    ax.axvspan(start, m, color=REG_C.get(prev, "#ccc"), alpha=0.28, lw=0)
                prev, start = v, m
        ax.axvspan(start, s.index[-1] + pd.offsets.MonthEnd(1), color=REG_C.get(prev, "#ccc"), alpha=0.28, lw=0)

    draw_bands(ax1, labels["final_label"].loc["2007-01-01":])
    ax1.plot(spy.index, spy.values, color=INK, lw=1.4)
    ax1.set_yscale("log")
    ax1.set_yticks([100, 200, 400, 800]); ax1.set_yticklabels(["100", "200", "400", "800"])
    ax1.set_title("국면 라벨 타임라인 (위: 사후 라벨 밴드 + SPY 로그가격 / 아래: 실시간 라벨)",
                  color=INK, fontsize=11, loc="left")
    ax1.legend(handles=[Patch(color=REG_C[r], alpha=0.4, label=REG_KR[r]) for r in REG_C],
               loc="upper left", frameon=False, fontsize=9, ncol=4)
    draw_bands(ax2, labels["realtime_label"].loc["2007-01-01":])
    ax2.set_yticks([]); ax2.set_ylabel("실시간", fontsize=8, rotation=0, ha="right", va="center")
    ax2.grid(False)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "regime_timeline.png"), dpi=150)
    plt.close(fig)

    # ---------- 차트 3: 셔플 분포 ----------
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.2))
    for ax, (nm, dist, act, pct) in zip(axes, [
            ("V1", sh_v1, metrics(df["V1"])["CAGR"], pct_v1),
            ("V2", sh_v2, metrics(df["V2"])["CAGR"], pct_v2)]):
        ax.hist(dist.CAGR * 100, bins=40, color="#9ec5f4", edgecolor=SURF, lw=0.5)
        ax.axvline(act * 100, color="#e34948", lw=2)
        ax.axvline(dist.CAGR.median() * 100, color=MUT, lw=1.2, ls="--")
        ax.annotate(f"실제 {nm}: {act*100:.1f}%\n({pct:.0f}퍼센타일)",
                    xy=(act * 100, ax.get_ylim()[1] * 0.9), color="#e34948",
                    fontsize=9, ha="left" if nm == "V2" else "right", va="top",
                    xytext=(act * 100 + (0.3 if nm == "V2" else -0.3), ax.get_ylim()[1] * 0.95))
        ax.set_title(f"{nm}: 라벨 셔플 1000회 CAGR 분포 (점선=셔플 중앙값)", color=INK, fontsize=10, loc="left")
        ax.set_xlabel("CAGR (%)")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "shuffle_distribution.png"), dpi=150)
    plt.close(fig)
    print("[out] 3 PNGs")

    # ---------- metrics_summary.md ----------
    m = {k: metrics(df[k]) for k in df.columns}
    ha_t = ha["t"]

    lines = []
    lines.append("```")
    lines.append("H-A (국면별 자산 아웃퍼폼):  실패  — 사후 라벨 기준 매핑 자산이 국면 내 1위인 곳은 봄(VNQ)뿐. "
                 f"겨울=TLT는 6개 자산 중 꼴찌(연 {ha_t.loc['Winter','TLT']:.1%}, SPY는 {ha_t.loc['Winter','SPY']:.1%}). "
                 "사후 라벨 로테이션(C4)조차 SPY·60/40에 완패")
    lines.append(f"H-B (실시간 판정 가능):      실패  — 라벨 지연 중앙값 {ok.delay_days.median():.0f}일, "
                 f"사후 전환 {len(delays)}회 중 {n_miss}회({n_miss/len(delays):.0%})는 실시간이 아예 미감지, "
                 "실시간·사후 라벨 일치율 73.6%")
    lines.append(f"C3 셔플 테스트:              V1 = 셔플 분포의 {pct_v1:.0f}퍼센타일(무작위보다 나쁨), "
                 f"V2 = {pct_v2:.0f}퍼센타일(무작위와 구분 불가)")
    lines.append("결론:                        (c) — 프레임 자체에 정보가 없다. 관측되는 효과(V2의 MDD 축소)는 "
                 "간절기·가을 판정으로 기간의 37%를 현금(BIL)에 둔 단순 자산배분 효과다")
    lines.append("```")
    lines.append("")
    lines.append("# 4계절 매크로 프레임 검증 — 측정 결과 (2007-01 ~ 2026-07)")
    lines.append("")
    lines.append("## 1. 표준 지표 (월간, 비용 왕복 10bp 반영, Sharpe는 rf=0)")
    lines.append("")
    lines.append("| 전략 | CAGR | 연변동성 | MDD | Calmar | Sharpe | 최대 원금하회(월) |")
    lines.append("|---|---|---|---|---|---|---|")
    name_map = {"V1": "V1 실시간(간절기=유지)", "V2": "V2 실시간(간절기=현금)",
                "C4_final_V1": "C4 사후라벨(V1방식)", "C4_final_V2": "C4 사후라벨(V2방식)",
                "C1_SPY": "C1 SPY 매수보유", "C2_6040": "C2 60/40 분기리밸", "C5_EW6": "C5 동일비중 6자산"}
    for k in ["V1", "V2", "C4_final_V1", "C4_final_V2", "C1_SPY", "C2_6040", "C5_EW6"]:
        x = m[k]
        lines.append(f"| {name_map[k]} | {fmt_pct(x['CAGR'])} | {fmt_pct(x['Vol'])} | {fmt_pct(x['MDD'])} "
                     f"| {x['Calmar']:.2f} | {x['Sharpe']:.2f} | {x['MaxUW_months']:.0f} |")
    lines.append("")
    lines.append("- V1은 20년 누적으로 **사실상 제로 수익**(CAGR 0.4%)이며 원금 하회 기간이 169개월(14년).")
    lines.append("- V2가 나아 보이는 이유는 로테이션이 아니라 **현금 보유 비중**: 간절기(85개월)+가을 판정 합산 "
                 "전체 기간의 37.3%를 BIL로 보냄(실측). 그 결과 MDD는 줄지만 CAGR은 SPY의 절반 이하.")
    lines.append("- **사후 라벨(C4, 순수 look-ahead)조차 SPY·60/40·동일비중 전부에 진다** — 실행 지연 이전에 "
                 "프레임의 자산 매핑 자체가 틀렸다는 뜻 (H-A 실패의 전략 차원 확인).")
    lines.append("")
    lines.append("## 2. H-A 직접 검증 — 사후 라벨 기준 국면×자산 연율화 평균수익 (동월)")
    lines.append("")
    hdr = "| 국면 (n개월) | " + " | ".join(ASSETS) + " | 매핑 자산 | 매핑 순위 |"
    lines.append(hdr)
    lines.append("|" + "---|" * (len(ASSETS) + 3))
    mapping = {"Spring": "VNQ", "Summer": "SPY+DBC", "Autumn": "BIL", "Winter": "TLT"}
    map_chk = {"Spring": "VNQ", "Summer": "SPY", "Autumn": "BIL", "Winter": "TLT"}
    for reg in ["Spring", "Summer", "Autumn", "Winter"]:
        row = ha_t.loc[reg]
        ranks = row[ASSETS].rank(ascending=False)
        cells = " | ".join(fmt_pct(row[a]) for a in ASSETS)
        lines.append(f"| {REG_KR[reg]} ({row['n']:.0f}) | {cells} | {mapping[reg]} | {int(ranks[map_chk[reg]])}/6 |")
    lines.append("")
    lines.append("- 지지되는 매핑은 **봄=VNQ(1위)** 하나. 여름은 DBC 1위·SPY 2위로 절반 지지.")
    lines.append("- **겨울=장기채(책의 핵심 주장)는 정면으로 반증**: 겨울 국면에서 TLT 연 0.0%로 6개 자산 중 꼴찌, "
                 "SPY가 +20.5%로 1위 (겨울 라벨의 상당수가 침체 후반 반등 국면 + 2022년 채권 폭락). "
                 "'금리 인하 시 장기채 최대 상승'은 고금리에서 출발할 때만 성립 — 저금리 20년 구간에는 부적용.")
    lines.append("- 익월(t+1) 기준으로 넓히면 **네 국면 모두 매핑 자산이 1위가 아님** — 관측 시점에서 한 달만 "
                 "지나도 매핑의 근거가 사라짐.")
    lines.append("")
    lines.append("**실패의 구조 — 축 선택 오류 (매핑 오류가 아님):**")
    lines.append("")
    lines.append("- **2020-03 사후 라벨 = 봄** (PMI 3mma 50.03, CPI 3개월 변화 −0.0083): 코로나 폭락이 벌어진 바로 그 달에 "
                 "look-ahead 라벨이 봄(=VNQ)을 지시. 유가 붕괴발 물가 급락을 프레임이 '경기 상승 + 물가 하락 = 봄'으로 "
                 "읽은 것. C4의 2020Q1 −28.3%가 여기서 나옴.")
    lines.append("- 경기·물가 두 축만으로는 **물가 하락의 원인**(생산성 개선·공급 확대 = 위험자산 국면 vs 수요 붕괴·신용 경색 "
                 "= 현금/국채 국면)을 구분할 수 없고, 원인에 따라 정반대 자산이 필요함. 2007년 신용 사이클 붕괴 중에도 "
                 "PMI·CPI 기준으론 봄/여름 조건이 성립. **신용 축이 없는 모든 2×2 매크로 프레임에 공통되는 결함**이며, "
                 "파라미터·자산 재매핑으로 고칠 수 없음.")
    lines.append("")
    lines.append("## 3. H-B — 실시간 판정 지연")
    lines.append("")
    lines.append(f"| 항목 | 값 |")
    lines.append(f"|---|---|")
    lines.append(f"| 사후 라벨 전환 횟수 | {len(delays)}회 (연 {len(delays)/19.5:.1f}회) |")
    lines.append(f"| 실시간 미감지 전환 | {n_miss}회 ({n_miss/len(delays):.0%}) |")
    lines.append(f"| 감지된 전환의 지연 | 중앙값 {ok.delay_days.median():.0f}일, IQR [{ok.delay_days.quantile(.25):.0f}, "
                 f"{ok.delay_days.quantile(.75):.0f}], 최대 {ok.delay_days.max():.0f}일 |")
    lines.append(f"| 지연 구간의 신규국면 자산 수익 (놓친 알파) | 전환당 평균 +1.1%, 19.5년 합계 +48.3%p |")
    lines.append(f"| 실시간·사후 라벨 월단위 일치율 | 73.6% |")
    lines.append("")
    lines.append("- 지연의 원천은 판정 기술이 아니라 **발표 지연 구조**: PMI는 익월 1~3영업일(28~35일), "
                 "CPI는 익월 중순(약 44일) 발표라 월말 판정은 항상 전월 데이터 기준. 이 1개월은 없앨 수 없다.")
    lines.append(f"- 국면 중앙 지속기간이 3개월(1~2개월짜리가 44%)인데 지연이 1개월+ → 짧은 국면은 구조적으로 "
                 "포착 불가(28% 미감지가 그 증거).")
    lines.append("")
    lines.append("## 4. C3 셔플 테스트 (라벨 run 단위 셔플 1000회, 비용 동일 적용, seed=42)")
    lines.append("")
    lines.append("| 전략 | 실제 CAGR | 셔플 중앙값 | CAGR 퍼센타일 | Sharpe 퍼센타일 |")
    lines.append("|---|---|---|---|---|")
    lines.append(f"| V1 | {fmt_pct(m['V1']['CAGR'])} | {fmt_pct(sh_v1.CAGR.median())} | {pct_v1:.0f} | {pct_v1_s:.0f} |")
    lines.append(f"| V2 | {fmt_pct(m['V2']['CAGR'])} | {fmt_pct(sh_v2.CAGR.median())} | {pct_v2:.0f} | {pct_v2_s:.0f} |")
    lines.append("")
    lines.append("- **V1은 무작위 라벨의 7퍼센타일** — 실시간 라벨이 정보가 없는 정도가 아니라 *해롭다*. "
                 "대표 사례(GFC): 간절기가 2007-06~2008-09 사실상 연속 True → 2007년 중반의 봄 라벨(VNQ)이 "
                 "위기 한복판까지 **14개월 동결** → 2008-2009 -37.5% vs SPY -18.1%. 코로나도 동일 구조"
                 "(간절기 2019-08~2020-04 연속 → 2019-07의 봄/VNQ를 폭락까지 유지). "
                 "PMI가 50 임계를 지나는 전환기가 곧 48~52 밴드라서, '간절기=직전 유지'는 **위기 진입기마다 "
                 "구식 위험자산 포지션을 동결하는 규칙**이 됨 — 구조적 결함이지 판정 오류가 아님.")
    lines.append("- V2는 58퍼센타일로 무작위와 구분 불가. 즉 V2의 성과는 라벨 정보가 아니라 현금 비중에서 온다.")
    lines.append("")
    lines.append("## 5. 국면 전이 행렬 (사후 라벨, 전환 시 조건부)")
    lines.append("")
    f_lab = fin["label"]
    ch = pd.crosstab(f_lab.shift(1)[f_lab != f_lab.shift(1)], f_lab[f_lab != f_lab.shift(1)], normalize="index")
    lines.append("| From\\To | 봄 | 여름 | 가을 | 겨울 |")
    lines.append("|---|---|---|---|---|")
    for r in ["Spring", "Summer", "Autumn", "Winter"]:
        cells = " | ".join(f"{ch.loc[r, c]:.2f}" if c in ch.columns and r in ch.index else "0.00"
                           for c in ["Spring", "Summer", "Autumn", "Winter"])
        lines.append(f"| {REG_KR[r]} | {cells} |")
    lines.append("")
    lines.append("- 순환 가설(봄→여름→가을→겨울)은 **기각**: 여름→봄 0.89, 겨울→가을 0.70 등 "
                 "**역방향·왕복 진동이 지배적**. 실제 구조는 물가 축이 자주 뒤집히며 봄↔여름, 겨울↔가을을 "
                 "왕복하는 2쌍의 진동이지 4계절 순환이 아니다.")
    lines.append("")
    lines.append("## 6. 산출물 및 데이터 한계 (정직 고지)")
    lines.append("")
    lines.append("- **ISM PMI(NAPM)는 FRED/ALFRED에서 삭제됨**(라이선스). 대체: investing.com 이벤트 히스토리의 "
                 "**최초발표치+실제 발표일**(1970~2026, 680건; 2020-04=41.5, 발표 2020-05-01 교차검증). "
                 "최초발표치 사용이라 실시간 검증엔 오히려 충실하나, PMI의 사후 수정분(연간 계절조정, 통상 ±1pt 미만)은 "
                 "사후 라벨에 반영 못함.")
    lines.append("- CPI·INDPRO·BUSINV는 ALFRED 전체 vintage 사용(발표일 실측: CPI 익월 중순 확인). "
                 "CMRMTSPL vintage는 2013-06 이후만 존재, HY OAS는 FRED API 3년 제한 — 둘 다 라벨에 미사용(보조).")
    lines.append("- BIL 상장(2007-05-30) 이전 현금 구간 수익률 0% 처리(당시 실제 현금수익 연 ~5% → 초기 "
                 "V2·가을 구간이 소폭 과소평가되나 결론 방향 불변).")
    lines.append("- Sharpe는 rf=0 기준(전 전략 동일 적용). 거래비용 왕복 10bp.")
    lines.append("- 간절기 판정은 PMI 3개월평균이 48~52 구간인 경우로 해석(지시서의 'PMI'가 원값인지 "
                 "3mma인지 미명시 → 경기 축과 동일 계열 사용).")

    with open(os.path.join(OUT, "metrics_summary.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print("[out] metrics_summary.md")

    # ---------- robustness.md ----------
    rl = []
    rl.append("# 강건성 검사 (지시서 6장)")
    rl.append("")
    rl.append("## 1. 서브샘플 분리")
    rl.append("")
    rl.append("| 구간 | V1 CAGR | V2 CAGR | SPY CAGR | V1−SPY | V2−SPY |")
    rl.append("|---|---|---|---|---|---|")
    for nm, s0, s1 in [("2007–2015", "2007-01-01", "2015-12-31"), ("2016–2025", "2016-01-01", "2025-12-31")]:
        sub = df.loc[s0:s1]
        mv1, mv2, ms = metrics(sub["V1"]), metrics(sub["V2"]), metrics(sub["C1_SPY"])
        rl.append(f"| {nm} | {fmt_pct(mv1['CAGR'])} | {fmt_pct(mv2['CAGR'])} | {fmt_pct(ms['CAGR'])} "
                  f"| {fmt_pct(mv1['CAGR'] - ms['CAGR'])} | {fmt_pct(mv2['CAGR'] - ms['CAGR'])} |")
    rl.append("")
    rl.append("- 두 구간 모두 초과수익 **음(−10%p 내외)으로 부호 일치** — '한 구간의 불운'이 아니라 일관된 열위.")
    rl.append("")
    rl.append("## 2. 전환 이벤트 수")
    rl.append("")
    rl.append(f"- 사후 라벨 전환 61회(> 30) → 표본수 자체는 통계 판단 가능선. 단 국면당 개월수가 "
              "가을 28·겨울 41로 얇아 국면별 자산수익 추정의 신뢰구간은 넓다 (H-A 판정은 순위 역전 "
              "폭이 커서 표본 문제로 뒤집힐 수준이 아님: 겨울 TLT 0.0% vs SPY 20.5%).")
    rl.append("")
    rl.append("## 3. 파라미터 민감도 (V1, 실시간 라벨 재계산)")
    rl.append("")
    rl.append("| PMI 임계 \\ CPI 창 | 1개월 | 3개월 | 6개월 | 현금(BIL) 비중 | 현금+TLT |")
    rl.append("|---|---|---|---|---|---|")
    for th in [48, 50, 52]:
        row = []
        for cw in [1, 3, 6]:
            r = sens[(sens.th == th) & (sens.cw == cw)].iloc[0]
            row.append(f"CAGR {fmt_pct(r.CAGR)} / Cal {r.Calmar:.2f}")
        sub = sens[sens.th == th]
        row.append(f"{sub.cash.min():.0%}~{sub.cash.max():.0%}")
        row.append(f"{sub.defensive.iloc[0]:.0%}")
        rl.append(f"| {th} | " + " | ".join(row) + " |")
    rl.append("")
    c_cal = sens.cash.corr(sens.Calmar); c_mdd = sens.cash.corr(sens.MDD)
    d_mdd = sens.defensive.corr(sens.MDD)
    rl.append("- CAGR 0.4%~7.7%로 **파라미터에 따라 20배 출렁이고 고원(plateau)이 없다.** 지시서 기본값(50/3)이 "
              "하필 **최악 셀**. 인접 셀 간 Calmar가 절반 이하로 갈리는 구조(52/1 0.35 vs 52/3 0.13) = "
              "신호가 아니라 노이즈에 대한 적합.")
    rl.append(f"- **정직 고지 — 52/1 셀은 Calmar 0.35로 SPY(0.21)·60/40(0.28)을 위험조정 기준 이김** "
              "(CAGR 7.7%는 SPY 10.9% 미만). 그러나 채택 근거가 못 되는 이유: ①고원 부재(인접 52/3이 0.13) "
              "②그 성과의 원천이 국면 판정이 아니라 **방어자산 비중**임이 측정됨 — 임계 52는 방어자산(BIL+TLT) "
              "비중을 50%로 밀어올리며(48은 6%, 50은 23%), 셀별 현금 비중과 성과의 상관이 "
              f"**corr(현금, Calmar)=+{c_cal:.2f}, corr(현금, MDD)=+{c_mdd:.2f}, corr(현금+TLT, MDD)=+{d_mdd:.2f}**. "
              "즉 민감도 표는 사실상 '현금 비중 표'다 — V2 셔플 58퍼센타일(라벨 정보 0)과 정확히 같은 이야기.")
    rl.append("- 참고: 본 구현의 간절기 밴드는 임계값 ±2로 함께 이동(임계 52 → 밴드 50~54). "
              "방어자산 비중은 CPI 창과 무관하게 임계값만으로 결정됨(각 행에서 동일) = 경기 축 임계가 "
              "자산배분 다이얼이라는 직접 증거.")
    rl.append("")
    rl.append("## 4. 위기 구간 분해 (누적수익, 전략 vs SPY)")
    rl.append("")
    rl.append("| 구간 | V1 | V2 | C4 사후 | SPY | 60/40 |")
    rl.append("|---|---|---|---|---|---|")
    for nm, s0, s1 in [("2008–2009 (GFC)", "2008-01-01", "2009-12-31"),
                       ("2020Q1 (코로나)", "2020-01-01", "2020-03-31"),
                       ("2022 (인플레)", "2022-01-01", "2022-12-31")]:
        sub = df.loc[s0:s1]; cum = (1 + sub).prod() - 1
        rl.append(f"| {nm} | {fmt_pct(cum['V1'])} | {fmt_pct(cum['V2'])} | {fmt_pct(cum['C4_final_V1'])} "
                  f"| {fmt_pct(cum['C1_SPY'])} | {fmt_pct(cum['C2_6040'])} |")
    rl.append("")
    rl.append("- 위기 방어 프레임인데 **GFC에서 V1 -37.5% < SPY -18.1%**. 원인은 판정 실패가 아니라 간절기 규칙: "
              "PMI 3mma가 48~52 밴드에 걸린 채 2007-06~2008-09가 사실상 연속 간절기 → V1은 2007년 중반의 봄 라벨"
              "(VNQ)을 위기 한복판까지 14개월 동결(그 기간 raw 라벨은 여름→겨울→가을로 이미 이동). "
              "**2020Q1 -28.3%도 동일 구조**: 실시간 raw 라벨은 2020-01~03 가을(PMI 3mma 48~49.6)이었으나 "
              "간절기가 2019-08~2020-04 연속 True라 2019-07의 봄(VNQ)을 폭락까지 유지. 같은 기간 V2는 현금 → +0.4%. "
              "즉 두 위기 모두 '간절기=유지' 규칙이 판정을 무력화한 사례로, V1/V2 격차 논거를 강화.")
    rl.append("- 사후 라벨(C4)은 GFC +13.7%로 방어했으나 2020Q1은 **look-ahead로도 -28.3%** — 2020-03 사후 라벨이 "
              "봄(디플레 쇼크를 '물가 하락=봄'으로 오독)이었기 때문. 위기 대응 실패가 실행 지연(H-B)만의 문제가 "
              "아니라 축 자체의 문제임을 보여줌 (metrics_summary.md '실패의 구조' 참조).")
    rl.append("- 유일하게 방어된 위기는 2022(V1 -1.2%, V2 +4.0% vs SPY -19.0%) — 인플레 국면은 물가 축이 "
              "느리게 움직여 실시간 판정이 따라갈 수 있었음. 단 1회 사례.")
    rl.append("")
    rl.append("## 5. V1 vs V2 격차 (지시서 3.3)")
    rl.append("")
    rl.append(f"- V1 CAGR {fmt_pct(m['V1']['CAGR'])} vs V2 {fmt_pct(m['V2']['CAGR'])}, MDD -58% vs -28%: "
              "간절기 처리 하나로 성과가 이만큼 갈림 = **프레임 강건성 부족의 직접 증거** "
              "(책이 규정하지 않은 공백이 성과의 대부분을 결정).")
    rl.append("- 격차의 메커니즘: PMI가 50 임계를 통과하는 전환기가 정의상 48~52 밴드 내부라서, 간절기는 "
              "정확히 국면이 바뀌는 순간마다 발동한다. V1(유지)은 그때마다 직전 위험자산을 동결(GFC 14개월, "
              "코로나 7개월)하고, V2(현금)는 그때마다 현금으로 피신 — V2의 상대 우위는 전부 여기서 나오며, "
              "이는 국면 '판정'이 아니라 '판정 불능 구간의 현금화'가 만든 성과다.")
    rl.append("")
    rl.append("## 6. 국면 지속기간 분포")
    rl.append("")
    g = durs.groupby("regime")["months"]
    rl.append("| 국면 | 횟수 | 평균 | 중앙값 | 최대 |")
    rl.append("|---|---|---|---|---|")
    for reg in ["Spring", "Summer", "Autumn", "Winter"]:
        s = g.get_group(reg)
        rl.append(f"| {REG_KR[reg]} | {len(s)} | {s.mean():.1f} | {s.median():.1f} | {s.max():.0f} |")
    rl.append(f"")
    rl.append(f"- 1~2개월짜리 국면이 **{(durs.months <= 2).mean():.0%}** — '계절'이라기보다 월간 노이즈. "
              "발표지연 1개월 구조와 결합하면 짧은 국면 대부분은 실행 불가능.")

    with open(os.path.join(OUT, "robustness.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(rl))
    print("[out] robustness.md")
    print("DONE")


if __name__ == "__main__":
    main()
