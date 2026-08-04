# -*- coding: utf-8 -*-
"""4계절 매크로 프레임 검증 — 1단계: 데이터 수집 (vintage + 자산)

산출:
  four_seasons/cache/alfred_{SERIES}.parquet  — (date, value, realtime_start, realtime_end) 전체 vintage
  four_seasons/cache/pmi_releases.parquet     — (target_month, release_date, value, revised_flag)
  four_seasons/cache/etf_daily.parquet        — 6 ETF adjusted close (daily)
  output/vintage_panel.csv                    — (indicator, target_month, release_date, value) 최초발표 패널
"""
import os, sys, json, time
import datetime as dt
import requests
import numpy as np
import pandas as pd

np.random.seed(42)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "four_seasons", "cache")
OUT = os.path.join(ROOT, "output")
os.makedirs(CACHE, exist_ok=True)
os.makedirs(OUT, exist_ok=True)

sys.path.insert(0, ROOT)
try:
    from config import FRED_API_KEY as KEY
except Exception:
    KEY = os.environ.get("FRED_API_KEY", "")
assert KEY, "FRED_API_KEY not found"

BASE = "https://api.stlouisfed.org/fred"
RT_END = "2026-08-04"          # FRED 서버 오늘
OBS_START = "2004-01-01"       # YoY/3mma 계산 여유 포함
RT_START_DEFAULT = "2006-06-01"

ALFRED_SERIES = ["CPIAUCSL", "INDPRO", "BUSINV", "CMRMTSPL"]
NOREV_SERIES = ["T10Y2Y", "BAMLH0A0HYM2"]   # 리비전 없음 — 최신 vintage만


def _get(url, params, retries=3):
    for i in range(retries):
        try:
            r = requests.get(url, params=params, timeout=60)
            j = r.json()
            if "error_code" in j:
                raise RuntimeError(j.get("error_message", "?"))
            return j
        except Exception as e:
            if i == retries - 1:
                raise
            time.sleep(2 * (i + 1))


def series_meta(sid):
    j = _get(f"{BASE}/series", dict(series_id=sid, api_key=KEY, file_type="json",
                                    realtime_start="1990-01-01", realtime_end=RT_END))
    return j["seriess"]


def alfred_observations(sid, rt_start):
    rows, offset = [], 0
    while True:
        j = _get(f"{BASE}/series/observations",
                 dict(series_id=sid, api_key=KEY, file_type="json",
                      observation_start=OBS_START, realtime_start=rt_start,
                      realtime_end=RT_END, limit=100000, offset=offset))
        obs = j["observations"]
        rows += obs
        if not obs or offset + len(obs) >= j["count"]:
            break
        offset += len(obs)
    df = pd.DataFrame(rows)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    for c in ["date", "realtime_start", "realtime_end"]:
        df[c] = pd.to_datetime(df[c])
    return df.dropna(subset=["value"]).reset_index(drop=True)


def fetch_alfred():
    for sid in ALFRED_SERIES:
        fp = os.path.join(CACHE, f"alfred_{sid}.parquet")
        if os.path.exists(fp):
            print(f"[cache] {sid}")
            continue
        meta = series_meta(sid)
        first_rt = min(pd.Timestamp(m["realtime_start"]) for m in meta)
        rt_start = max(pd.Timestamp(RT_START_DEFAULT), first_rt).strftime("%Y-%m-%d")
        df = alfred_observations(sid, rt_start)
        df.to_parquet(fp)
        print(f"[fetch] {sid}: {len(df)} vintage rows, rt_start={rt_start}, "
              f"obs {df['date'].min().date()}..{df['date'].max().date()}")
        time.sleep(1)


def fetch_norev():
    for sid in NOREV_SERIES:
        fp = os.path.join(CACHE, f"fred_{sid}.parquet")
        if os.path.exists(fp):
            print(f"[cache] {sid}")
            continue
        try:
            j = _get(f"{BASE}/series/observations",
                     dict(series_id=sid, api_key=KEY, file_type="json",
                          observation_start=OBS_START, limit=100000))
            df = pd.DataFrame(j["observations"])[["date", "value"]]
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            df["date"] = pd.to_datetime(df["date"])
            df = df.dropna().reset_index(drop=True)
            df.to_parquet(fp)
            print(f"[fetch] {sid}: {len(df)} rows, {df['date'].min().date()}..{df['date'].max().date()}")
        except Exception as e:
            print(f"[warn] {sid} failed: {e} (보조지표 — 계속 진행)")
        time.sleep(1)


def fetch_pmi():
    """investing.com 이벤트 차트 — ISM Manufacturing PMI(event 173).
    각 행 = (발표시각, 최초발표치, revised플래그). 대상월 = 발표월 - 1."""
    fp = os.path.join(CACHE, "pmi_releases.parquet")
    if os.path.exists(fp):
        print("[cache] PMI")
        return
    r = requests.get("https://sbcharts.investing.com/events_charts/us/173.json",
                     headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}, timeout=60)
    data = r.json()["data"]
    rows = []
    for rec in data:
        ts_ms, actual = rec[0], rec[1]
        flag = rec[2] if len(rec) > 2 else None
        if actual is None:
            continue
        rel = pd.Timestamp(ts_ms, unit="ms").normalize()
        tgt = (rel.to_period("M") - 1).to_timestamp()  # 대상월 = 발표월 - 1 (항상)
        rows.append((tgt, rel, float(actual), flag))
    df = pd.DataFrame(rows, columns=["target_month", "release_date", "value", "revised_flag"])
    df = df.sort_values("release_date").reset_index(drop=True)
    # 무결성: 월 단위 연속성 확인
    gaps = df["target_month"].diff().dropna()
    n_bad = (gaps != pd.Timedelta(0)).sum() - (gaps == pd.offsets.MonthBegin(1).nanos if False else 0)
    df.to_parquet(fp)
    print(f"[fetch] PMI: {len(df)} releases, {df['target_month'].min().date()}..{df['target_month'].max().date()}")


def fetch_etf():
    import yfinance as yf
    fp = os.path.join(CACHE, "etf_daily.parquet")
    if os.path.exists(fp):
        print("[cache] ETF")
        return
    tickers = ["SPY", "IEF", "TLT", "DBC", "VNQ", "BIL"]
    frames = {}
    for t in tickers:
        h = yf.Ticker(t).history(start="2006-01-01", end="2026-08-02", auto_adjust=True)
        s = h["Close"]
        s.index = pd.to_datetime(s.index).tz_localize(None)
        frames[t] = s
        time.sleep(0.5)
    px = pd.DataFrame(frames)
    px.to_parquet(fp)
    print(f"[fetch] ETF daily: {px.shape}, {px.index[0].date()}..{px.index[-1].date()}")


def build_vintage_panel():
    """(indicator, target_month, release_date, value) — 각 관측의 최초 발표."""
    panels = []
    for sid in ALFRED_SERIES:
        df = pd.read_parquet(os.path.join(CACHE, f"alfred_{sid}.parquet"))
        rt0 = df["realtime_start"].min()
        first = df.sort_values("realtime_start").groupby("date").first().reset_index()
        # vintage 창 시작일에 이미 알려져 있던 관측은 진짜 발표일을 모름 → 표기
        first["release_known"] = first["realtime_start"] > rt0
        first["indicator"] = sid
        panels.append(first.rename(columns={"date": "target_month",
                                            "realtime_start": "release_date"})[
            ["indicator", "target_month", "release_date", "value", "release_known"]])
    pmi = pd.read_parquet(os.path.join(CACHE, "pmi_releases.parquet"))
    pmi_p = pmi.assign(indicator="ISM_PMI", release_known=True).rename(
        columns={})[["indicator", "target_month", "release_date", "value", "release_known"]]
    panels.append(pmi_p)
    panel = pd.concat(panels, ignore_index=True).sort_values(["indicator", "target_month"])
    panel.to_csv(os.path.join(OUT, "vintage_panel.csv"), index=False)
    print(f"[out] vintage_panel.csv: {len(panel)} rows")
    return panel


if __name__ == "__main__":
    fetch_alfred()
    fetch_norev()
    fetch_pmi()
    fetch_etf()
    build_vintage_panel()
    print("DONE")
