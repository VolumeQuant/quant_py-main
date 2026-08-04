# -*- coding: utf-8 -*-
"""4계절 검증 — 3단계: 백테스트 (V1/V2, 대조군 C1~C5, 셔플 MC, 강건성)

실행 규칙 (지시서 3.4):
  - 라벨은 월말 vintage로 판정, 익월 첫 거래일 종가 리밸런싱
  - 거래비용 왕복 10bp (완전교체 시 10bp = 0.001 × Σ|Δw|/2)
자산 매핑: 봄=VNQ / 여름=SPY50+DBC50 / 가을=BIL / 겨울=TLT
V1: 간절기(PMI3mma 48~52) → 직전 국면 유지 / V2: 간절기 → BIL
BIL 상장(2007-05-30) 이전 현금 수익률 = 0% (문서화된 한계)
"""
import os
import numpy as np
import pandas as pd

np.random.seed(42)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "four_seasons", "cache")
OUT = os.path.join(ROOT, "output")

import sys
sys.path.insert(0, os.path.join(ROOT, "four_seasons"))
from fs_labels import load_data, realtime_labels, final_labels, measure_delays

REGIME_W = {
    "Spring": {"VNQ": 1.0},
    "Summer": {"SPY": 0.5, "DBC": 0.5},
    "Autumn": {"BIL": 1.0},
    "Winter": {"TLT": 1.0},
    "Cash":   {"BIL": 1.0},
}
ASSETS = ["SPY", "IEF", "TLT", "DBC", "VNQ", "BIL"]
COST_RT = 0.0010  # 왕복 10bp
START = "2007-01-01"


# ---------- 수익률 인프라 ----------

def load_prices():
    px = pd.read_parquet(os.path.join(CACHE, "etf_daily.parquet"))
    # BIL 상장 전: 가격 평탄 backfill = 0% 수익률 현금
    first = px["BIL"].first_valid_index()
    px.loc[:first, "BIL"] = px.loc[first, "BIL"]
    return px


def rebalance_returns(px):
    """월별 리밸런스 구간 수익률: 각 월 첫 거래일 종가 → 다음 월 첫 거래일 종가"""
    firsts = px.groupby(px.index.to_period("M")).head(1).index
    pts = px.loc[firsts].copy()
    rets = pts.pct_change().shift(-1)  # row m = 구간 [m월 첫거래일, m+1월 첫거래일) 수익
    rets.index = rets.index.to_period("M").to_timestamp()
    return rets.dropna(how="all"), firsts


def weights_from_labels(eff_labels):
    w = pd.DataFrame(0.0, index=eff_labels.index, columns=ASSETS)
    for m, lab in eff_labels.items():
        for a, x in REGIME_W[lab].items():
            w.loc[m, a] = x
    return w


def portfolio_returns(eff_labels, rets):
    """eff_labels: 판정월 m 인덱스 (포지션은 m+1월 구간에 적용)"""
    w = weights_from_labels(eff_labels)
    w.index = w.index + pd.offsets.MonthBegin(1)  # 적용월로 시프트
    common = w.index.intersection(rets.index)
    w, r = w.loc[common], rets.loc[common, ASSETS].fillna(0.0)
    gross = (w * r).sum(axis=1)
    turnover = w.diff().abs().sum(axis=1) * 0.5
    turnover.iloc[0] = 0.5 * w.iloc[0].abs().sum()  # 최초 진입
    net = gross - COST_RT * turnover
    return net, turnover


def effective_labels(df, variant):
    """V1: 간절기=직전 유지 / V2: 간절기=Cash"""
    labs, prev = [], None
    for m, row in df.iterrows():
        if row["interseason"]:
            lab = (prev if (variant == "V1" and prev is not None) else "Cash")
        else:
            lab = row["label"]
        labs.append(lab)
        prev = lab
    return pd.Series(labs, index=df.index)


# ---------- 지표 ----------

def metrics(r, freq=12):
    r = r.dropna()
    if len(r) == 0:
        return {}
    eq = (1 + r).cumprod()
    yrs = len(r) / freq
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    vol = r.std() * np.sqrt(freq)
    dd = eq / eq.cummax() - 1
    mdd = dd.min()
    calmar = cagr / abs(mdd) if mdd < 0 else np.nan
    sharpe = r.mean() / r.std() * np.sqrt(freq) if r.std() > 0 else np.nan
    under = (dd < 0)
    max_uw, cur = 0, 0
    for u in under:
        cur = cur + 1 if u else 0
        max_uw = max(max_uw, cur)
    return dict(CAGR=cagr, Vol=vol, MDD=mdd, Calmar=calmar, Sharpe=sharpe, MaxUW_months=max_uw)


# ---------- 대조군 ----------

def control_returns(rets):
    out = {}
    out["C1_SPY"] = rets["SPY"].copy()
    # C2: 60/40 분기 리밸런싱 (1/4/7/10월 첫 거래일)
    w = None
    rows = []
    for m, row in rets.iterrows():
        if w is None or m.month in (1, 4, 7, 10):
            w = np.array([0.6, 0.4])
        r = np.array([row["SPY"], row["IEF"]])
        rows.append((w * r).sum())
        w = w * (1 + r); w = w / w.sum()
    out["C2_6040"] = pd.Series(rows, index=rets.index)
    # C5: 6자산 동일비중 월간 리밸런싱 (완전교체 아님 — 드리프트→EW 재조정 비용)
    ew = rets[ASSETS].fillna(0.0).mean(axis=1)
    # 월간 EW 리밸 비용: 자산 간 수익률 분산에 따른 드리프트 회전 (근사: 평균 |r_i - r_ew|/6 /2)
    drift = rets[ASSETS].fillna(0.0).sub(ew, axis=0).abs().mean(axis=1) / 2
    out["C5_EW6"] = ew - COST_RT * drift
    return out


# ---------- 셔플 (C3) ----------

def shuffle_test(eff_labels, rets, n=1000, seed=42):
    """국면 run 단위 셔플 (지속기간 구조 보존) → 동일 매핑·비용 백테스트"""
    rng = np.random.default_rng(seed)
    seq = eff_labels.values
    runs = []
    s = 0
    for i in range(1, len(seq) + 1):
        if i == len(seq) or seq[i] != seq[s]:
            runs.append(seq[s:i]); s = i
    stats = []
    for _ in range(n):
        order = rng.permutation(len(runs))
        shuf = np.concatenate([runs[i] for i in order])
        lab = pd.Series(shuf, index=eff_labels.index)
        r, _ = portfolio_returns(lab, rets)
        m = metrics(r)
        stats.append((m["CAGR"], m["Sharpe"], m["Calmar"]))
    return pd.DataFrame(stats, columns=["CAGR", "Sharpe", "Calmar"])


def pct_rank(dist, x):
    return (dist < x).mean() * 100


# ---------- 메인 ----------

def main():
    cpi, pmi = load_data()
    px = load_prices()
    rets, firsts = rebalance_returns(px)
    rets = rets[rets.index >= "2006-12-01"]

    months = pd.date_range("2006-11-01", "2026-06-01", freq="MS")
    rt = realtime_labels(cpi, pmi, months)
    fin = final_labels(cpi, pmi, months)

    # 전략
    res = {}
    turns = {}
    eff = {}
    for v in ["V1", "V2"]:
        e = effective_labels(rt, v)
        eff[v] = e
        res[v], turns[v] = portfolio_returns(e, rets)
    # C4: 사후 라벨 (V1 방식 간절기 처리)
    e4 = effective_labels(fin, "V1")
    res["C4_final_V1"], _ = portfolio_returns(e4, rets)
    e4b = effective_labels(fin, "V2")
    res["C4_final_V2"], _ = portfolio_returns(e4b, rets)

    res.update(control_returns(rets.loc[res["V1"].index]))

    # 공통 기간 정렬 (2007-01 ~)
    df = pd.DataFrame(res)
    df = df[df.index >= START].dropna(how="all")
    df.to_csv(os.path.join(OUT, "backtest_results.csv"))

    print("=== 지표 (2007-01 ~ %s) ===" % df.index[-1].strftime("%Y-%m"))
    tbl = pd.DataFrame({k: metrics(df[k]) for k in df.columns}).T
    print(tbl.round(3).to_string())

    for v in ["V1", "V2"]:
        e = eff[v].loc[df.index.min() - pd.offsets.MonthBegin(1):]
        n_trans = (e != e.shift(1)).sum() - 1
        print(f"{v}: transitions={n_trans} ({n_trans / (len(e)/12):.1f}/yr), "
              f"avg one-way turnover/yr={turns[v].loc[df.index].sum() / (len(df)/12):.2f}")

    # C3 셔플
    print("\n=== C3 셔플 (1000회, run 단위) ===")
    sh = {}
    for v in ["V1", "V2"]:
        e = eff[v][eff[v].index >= "2006-12-01"]
        dist = shuffle_test(e, rets, n=1000, seed=42)
        act = metrics(df[v])
        sh[v] = (dist, act)
        dist.to_csv(os.path.join(OUT, f"shuffle_dist_{v}.csv"), index=False)
        print(f"{v}: actual CAGR={act['CAGR']:.2%} -> pct {pct_rank(dist.CAGR, act['CAGR']):.0f} | "
              f"Sharpe={act['Sharpe']:.2f} -> pct {pct_rank(dist.Sharpe, act['Sharpe']):.0f} | "
              f"Calmar={act['Calmar']:.2f} -> pct {pct_rank(dist.Calmar, act['Calmar']):.0f}")
        print(f"   shuffle median CAGR={dist.CAGR.median():.2%}, Sharpe={dist.Sharpe.median():.2f}")

    # 전이행렬 (사후 라벨)
    print("\n=== 국면 전이행렬 (사후, 월단위) ===")
    f = fin["label"]
    tm = pd.crosstab(f.shift(1), f, normalize="index")
    print(tm.round(2).to_string())
    print("\n[전환시 조건부 (self 제외)]")
    ch = pd.crosstab(f.shift(1)[f != f.shift(1)], f[f != f.shift(1)], normalize="index")
    print(ch.round(2).to_string())

    # 국면 지속기간
    seq = fin["label"].values
    durs = []
    s = 0
    for i in range(1, len(seq) + 1):
        if i == len(seq) or seq[i] != seq[s]:
            durs.append((seq[s], i - s)); s = i
    dd = pd.DataFrame(durs, columns=["regime", "months"])
    print("\n=== 국면 지속기간 (개월) ===")
    print(dd.groupby("regime")["months"].describe()[["count", "mean", "50%", "max"]].round(1).to_string())
    print("1~2개월 국면 비율: %.0f%%" % ((dd.months <= 2).mean() * 100))
    dd.to_csv(os.path.join(OUT, "regime_durations.csv"), index=False)

    # 지연 구간 수익률 (놓친 알파)
    delays = measure_delays(rt, fin, px.index)
    miss_ret = []
    for _, row in delays.dropna(subset=["realtime_trade"]).iterrows():
        if row.delay_days and row.delay_days > 0:
            wmap = REGIME_W[row.regime]
            seg = px.loc[row.hindsight_trade:row.realtime_trade, list(wmap)]
            if len(seg) > 1:
                r = sum(wmap[a] * (seg[a].iloc[-1] / seg[a].iloc[0] - 1) for a in wmap)
                miss_ret.append(r)
    miss = pd.Series(miss_ret)
    print(f"\n=== 지연 구간 신규국면 수익 (놓친 알파) === n={len(miss)}, "
          f"mean={miss.mean():.2%}, median={miss.median():.2%}, sum={miss.sum():.1%}")

    # ---------- 강건성 ----------
    print("\n=== 파라미터 민감도 (V1, 실시간 라벨 재계산) ===")
    sens = []
    for th in [48, 50, 52]:
        for cw in [1, 3, 6]:
            r2 = realtime_labels(cpi, pmi, months, pmi_thresh=th, cpi_window=cw, band=2.0)
            e2 = effective_labels(r2, "V1")
            pr, _ = portfolio_returns(e2, rets)
            pr = pr[pr.index >= START]
            m2 = metrics(pr)
            cash = e2.isin(["Cash", "Autumn"]).mean()
            dfn = e2.isin(["Cash", "Autumn", "Winter"]).mean()
            sens.append(dict(th=th, cw=cw, CAGR=m2["CAGR"], MDD=m2["MDD"], Calmar=m2["Calmar"],
                             cash=cash, defensive=dfn))
            print(f"  thresh={th}, cpi_win={cw}: CAGR={m2['CAGR']:.2%}, MDD={m2['MDD']:.1%}, "
                  f"Calmar={m2['Calmar']:.2f}, cash={cash:.0%}")
    pd.DataFrame(sens).to_csv(os.path.join(OUT, "sensitivity_surface.csv"), index=False)

    print("\n=== 서브샘플 ===")
    for nm, s0, s1 in [("2007-2015", "2007-01-01", "2015-12-31"), ("2016-2025", "2016-01-01", "2025-12-31")]:
        sub = df.loc[s0:s1]
        row = {k: metrics(sub[k]) for k in ["V1", "V2", "C1_SPY", "C2_6040", "C5_EW6"]}
        t = pd.DataFrame(row).T[["CAGR", "Sharpe", "MDD"]]
        print(f"[{nm}]"); print(t.round(3).to_string())
        excess = metrics(sub["V1"])["CAGR"] - metrics(sub["C1_SPY"])["CAGR"]
        print(f"  V1 - SPY CAGR: {excess:+.2%}")

    print("\n=== 위기 구간 (누적수익) ===")
    for nm, s0, s1 in [("2008-2009", "2008-01-01", "2009-12-31"),
                       ("2020Q1", "2020-01-01", "2020-03-31"),
                       ("2022", "2022-01-01", "2022-12-31")]:
        sub = df.loc[s0:s1]
        cum = (1 + sub).prod() - 1
        print(f"[{nm}] V1={cum['V1']:.1%}, V2={cum['V2']:.1%}, SPY={cum['C1_SPY']:.1%}, "
              f"60/40={cum['C2_6040']:.1%}, C4final={cum['C4_final_V1']:.1%}")

    print("\nDONE")


if __name__ == "__main__":
    main()
