# -*- coding: utf-8 -*-
"""Deflated Sharpe Ratio (DSR) / Probabilistic Sharpe Ratio (PSR) 유틸리티.

Bailey & Lopez de Prado (2012 "The Sharpe Ratio Efficient Frontier",
2014 "The Deflated Sharpe Ratio") 공식의 자체 구현 (~100줄, 외부 purgedcv 미사용).

배경: 이 저장소는 7.4년 동일 데이터에서 backtest/_*.py 수백 개 변형을 실험해왔는데,
채택 기준(noise ±0.10 + WF + LOWO + 인접CV)에 "몇 번 시도했는가"에 대한 보정이 없다.
DSR은 n_trials번 중 최고 Sharpe를 골랐을 때 기대되는 최대 Sharpe(순수 운으로도 나올 값)를
벤치마크로 삼아, 관측된 Sharpe가 그걸 통계적으로 넘는지(p-value 형태로) 검정한다.

★채택 게이트 제안 문구(초안): "신규 룰/필터는 기존 noise±0.10·WF·LOWO·인접CV 통과 후,
연구 과정에서 시도한 근사 변형 수를 n_trials로 넣어 DSR(K10 쿨다운 등) ≥ 0.95를 추가 요구한다."

CLI: python backtest/deflated_sharpe.py <daily_returns.csv> --trials 30
     (csv 1열 = 일수익률, 헤더 무관 첫 열 사용)
     python backtest/deflated_sharpe.py --selftest
"""
import sys
import argparse
import numpy as np
import pandas as pd
from scipy import stats

CASH_ANNUAL = 0.03          # 현금 기회비용 3%/년 (production 가정과 동일)


def _rf_daily(freq):
    return CASH_ANNUAL / freq


def _excess(returns, freq=252):
    r = np.asarray(pd.Series(returns).dropna(), dtype=float)
    return r - _rf_daily(freq)


def sharpe(returns, freq=252):
    """연율화 Sharpe (현금 3%/freq 차감)."""
    ex = _excess(returns, freq)
    sd = ex.std(ddof=1)
    if len(ex) < 2 or sd == 0:
        return 0.0
    return float(ex.mean() / sd * np.sqrt(freq))


def _period_stats(returns, freq=252):
    """기간(비연율화) SR_hat, skew, kurtosis(정규=3), n — PSR/DSR 공식 입력."""
    ex = _excess(returns, freq)
    n = len(ex)
    sd = ex.std(ddof=1)
    sr_hat = 0.0 if (n < 2 or sd == 0) else float(ex.mean() / sd)
    skew = float(stats.skew(ex)) if n >= 3 else 0.0
    kurt = float(stats.kurtosis(ex, fisher=False)) if n >= 4 else 3.0  # 정규분포=3
    return sr_hat, skew, kurt, n


def psr(returns, sr_benchmark=0.0, freq=252):
    """Probabilistic Sharpe Ratio — 관측 SR이 sr_benchmark(기간 단위)를 넘을 확률.

    Bailey & Lopez de Prado (2012) 식:
    PSR = Phi[ (SR_hat - SR*) * sqrt(n-1) / sqrt(1 - skew*SR_hat + (kurt-1)/4 * SR_hat^2) ]
    (SR_hat, SR* 모두 기간[비연율화] 단위, n = 관측치 수, skew/kurt은 초과수익률 표본적률)
    """
    sr_hat, skew, kurt, n = _period_stats(returns, freq)
    if n < 3:
        return 0.5
    denom = 1 - skew * sr_hat + (kurt - 1) / 4.0 * sr_hat ** 2
    denom = max(denom, 1e-12) ** 0.5
    z = (sr_hat - sr_benchmark) * np.sqrt(n - 1) / denom
    return float(stats.norm.cdf(z))


def _expected_max_sr(n_trials, sr_std):
    """E[max SR_n] 근사 (Bailey&LdP 2014 식) — n_trials개 독립시도 중 최댓값의 기댓값.
    sr_std = trials 간 SR(기간단위) 표준편차."""
    if n_trials is None or n_trials <= 1:
        return 0.0
    euler_gamma = 0.5772156649015329
    n = float(n_trials)
    z1 = stats.norm.ppf(1 - 1.0 / n)
    z2 = stats.norm.ppf(1 - 1.0 / (n * np.e))
    return sr_std * ((1 - euler_gamma) * z1 + euler_gamma * z2)


def dsr(returns, n_trials, sr_variance=None, freq=252):
    """Deflated Sharpe Ratio — PSR(SR* = E[max SR over n_trials]).

    sr_variance: trials들의 기간단위 SR 분산 추정치. 미지정 시 Lo(2002) 점근분산의
    지배항으로 근사: Var(SR_hat) ~= (1 + 0.5*SR_hat^2) / n (관측 SR^2에 0.5 계수를
    곱한 항이 지배적 — "0.5×관측SR²"로 근사, 표본이 작을수록/SR이 작을수록 1/n항이
    보태져 보수적으로[분산을 더 크게] 잡는다).
    """
    sr_hat, _, _, n = _period_stats(returns, freq)
    if n_trials is None or n_trials <= 1:
        # 시도 1번 = 다중검정 보정 없음 → DSR == PSR(벤치마크 0)
        return psr(returns, sr_benchmark=0.0, freq=freq)
    if sr_variance is None:
        sr_variance = (1.0 + 0.5 * sr_hat ** 2) / max(n, 2)
    sr_std = max(sr_variance, 1e-12) ** 0.5
    sr_star = _expected_max_sr(n_trials, sr_std)
    return psr(returns, sr_benchmark=sr_star, freq=freq)


def evaluate(returns, n_trials, label="", freq=252):
    """SR/PSR/DSR 한 번에 계산 + 게이트 판정 프린트. dict 반환."""
    sr = sharpe(returns, freq)
    p = psr(returns, sr_benchmark=0.0, freq=freq)
    d = dsr(returns, n_trials, freq=freq)
    verdict = "PASS (유의)" if d >= 0.95 else "WARN (다중검정 보정 후 유의성 부족)"
    print(f"[{label}] n_trials={n_trials}  연율화SR={sr:.3f}  PSR(SR>0)={p:.4f}  "
          f"DSR={d:.4f}  -> {verdict}")
    return {"label": label, "n_trials": n_trials, "sharpe": sr, "psr": p, "dsr": d,
            "verdict": verdict}


# ---------------------------------------------------------------- selftest --
def _selftest():
    rng = np.random.default_rng(42)
    ok = True

    # ①순수 노이즈(SR≈0), trials=100 → DSR 낮아야 함
    noise = rng.normal(0.0003, 0.01, 1500)  # ~cash 수준 평균, DSR은 낮아야
    r1 = evaluate(noise, n_trials=100, label="selftest1_noise")
    p1 = r1["dsr"] < 0.5
    print(f"  -> 기대: DSR < 0.5  {'OK' if p1 else 'FAIL'}")
    ok &= p1

    # ②강한 진짜 알파(일 +0.3%, sigma 1%), trials=100 → DSR≈1
    alpha = rng.normal(0.003, 0.01, 1500)
    r2 = evaluate(alpha, n_trials=100, label="selftest2_strong_alpha")
    p2 = r2["dsr"] > 0.95
    print(f"  -> 기대: DSR > 0.95  {'OK' if p2 else 'FAIL'}")
    ok &= p2

    # ③trials=1이면 DSR==PSR
    mixed = rng.normal(0.001, 0.012, 800)
    d3 = dsr(mixed, n_trials=1)
    p3v = psr(mixed, sr_benchmark=0.0)
    p3 = abs(d3 - p3v) < 1e-9
    print(f"[selftest3_trials1] DSR={d3:.6f} PSR={p3v:.6f} -> 기대: 동일  {'OK' if p3 else 'FAIL'}")
    ok &= p3

    print("\n=== selftest " + ("ALL PASS" if ok else "FAIL") + " ===")
    return ok


def _main():
    ap = argparse.ArgumentParser(description="Deflated Sharpe Ratio / PSR 게이트 계산기")
    ap.add_argument("csv", nargs="?", help="일수익률 csv (1열, 헤더무관 첫 열 사용)")
    ap.add_argument("--trials", type=int, default=1, help="n_trials (연구 중 시도한 변형 수)")
    ap.add_argument("--selftest", action="store_true", help="합성데이터 단위테스트 3종 실행")
    args = ap.parse_args()

    if args.selftest or not args.csv:
        ok = _selftest()
        sys.exit(0 if ok else 1)

    df = pd.read_csv(args.csv, header=None)
    # 헤더가 있었으면 첫 값이 문자열 → NaN 처리되어 dropna로 제거됨
    returns = pd.to_numeric(df.iloc[:, 0], errors="coerce").dropna().values
    evaluate(returns, n_trials=args.trials, label=args.csv)


if __name__ == "__main__":
    _main()
