# -*- coding: utf-8 -*-
"""WISEfn(FnGuide 계열) NTM 소스 — 야후 eps_trend 커버리지 열화(111→73/일) 대응 (2026-07-10).

전략 (2단계 전환의 1단계):
  - current NTM: WISEfn 우선 (fusion_consensus_cache.csv, 매일 ~550종목 축적 중)
  - 7d/30d/60d/90d 스냅샷: WISEfn 자체 축적(6/25~)이 해당 지평을 커버하면 그것, 아니면 야후 값
  - 야후 완전 실패 종목도 WISEfn 이력이 30d 이상이면 편입 가능 (이력 쌓일수록 자동 확대 = 2단계)
데이터: fusion_consensus_cache.csv (date, ticker[6자리], forward_eps=NTM 합성, analyst_count, ...)
킬스위치: env KR_EPS_WISEFN_DISABLE=1 → 전부 야후 단독(구동작).
"""
import os
import pandas as pd
from datetime import timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_CSV = os.path.join(HERE, 'fusion_consensus_cache.csv')

_cache = None  # {ticker6: DataFrame(date_ts, forward_eps)} lazy


def _load():
    global _cache
    if _cache is not None:
        return _cache
    _cache = {}
    if os.environ.get('KR_EPS_WISEFN_DISABLE') == '1':
        return _cache
    try:
        df = pd.read_csv(CACHE_CSV, dtype={'ticker': str})
        df = df[df['forward_eps'].notna() & (df['forward_eps'] > 0)].copy()
        df['ticker'] = df['ticker'].str.zfill(6)
        df['date_ts'] = pd.to_datetime(df['date'].astype(str), format='%Y%m%d')
        for t, g in df.groupby('ticker'):
            _cache[t] = g.sort_values('date_ts')[['date_ts', 'forward_eps']]
    except Exception:
        _cache = {}
    return _cache


def to_ticker6(yahoo_ticker):
    """'005930.KS'/'035720.KQ' → '005930'"""
    return str(yahoo_ticker).split('.')[0].zfill(6)


def _value_at(g, ref_ts, tolerance_days=8):
    """ref 시점 이전 가장 가까운 값 (tolerance 내). 없으면 None."""
    sub = g[g['date_ts'] <= ref_ts]
    if len(sub) == 0:
        return None
    row = sub.iloc[-1]
    if (ref_ts - row['date_ts']).days > tolerance_days:
        return None
    return float(row['forward_eps'])


def wisefn_ntm(yahoo_ticker, today):
    """5스냅샷 NTM dict (없는 지평은 None). 종목 미커버면 None 반환.
    current는 최신값(5영업일 내), 과거 지평은 축적 이력에서 추출."""
    g = _load().get(to_ticker6(yahoo_ticker))
    if g is None or len(g) == 0:
        return None
    today_ts = pd.Timestamp(today.date() if hasattr(today, 'date') else today)
    cur = _value_at(g, today_ts, tolerance_days=7)
    if cur is None:
        return None
    out = {'current': cur}
    for key, days in [('7d', 7), ('30d', 30), ('60d', 60), ('90d', 90)]:
        out[key] = _value_at(g, today_ts - timedelta(days=days), tolerance_days=8)
    return out


def merge_ntm(yahoo_ntm, wf_ntm):
    """★소스 단일화 규칙 (지평별 혼합 금지 — 벤더 간 컨센 레벨 차이가 이음새에서
    가짜 리비전 점프를 만들기 때문. 한 종목의 5지평은 반드시 한 소스로만):
      1) WISEfn 이력이 90d까지 실측 완비 → 통째로 WISEfn (2단계 완전 전환, 자동)
      2) 야후 정상 → 통째로 야후 (구동작 유지)
      3) 야후 실패 + WISEfn 30d 실측 이상 → WISEfn (60/90d 결측은 최원거리 값으로 채움
         = 그 구간 리비전 중립. 야후에서 사라진 종목 구제용)
      4) 둘 다 불가 → None
    반환 (ntm_dict or None, source_tag)."""
    # 1) WISEfn 완비 → 완전 전환
    if wf_ntm and all(wf_ntm.get(k) is not None for k in ['current', '7d', '30d', '60d', '90d']):
        return dict(wf_ntm), 'wisefn_full'
    # 2) 야후 정상 → 야후 단일
    if yahoo_ntm is not None:
        return yahoo_ntm, 'yahoo'
    # 3) 야후 실패 → WISEfn 구제 (30d 실측 필수)
    if wf_ntm and wf_ntm.get('current') is not None and wf_ntm.get('30d') is not None:
        out = dict(wf_ntm)
        if out['7d'] is None:
            out['7d'] = out['current']
        if out['60d'] is None:
            out['60d'] = out['30d']
        if out['90d'] is None:
            out['90d'] = out['60d']
        return out, 'wisefn_rescue'
    return None, 'none' if not wf_ntm else 'insufficient_history'


def coverage_alert_line(today_count, recent_counts):
    """수집수 급감 경보 (fusion 6/30 경보와 동형). recent_counts=직전 7세션 리스트."""
    if not recent_counts:
        return ''
    base = sorted(recent_counts)[len(recent_counts) // 2]  # median
    if base > 0 and today_count < base * 0.8:
        return (f"⚠️ NTM 수집 급감: 오늘 {today_count}종목 (최근 중앙값 {base}) — "
                f"데이터 소스 점검 필요")
    return ''


def history_rewrite_check(db_path, today_str, tol=0.03):
    """★야후 이력 재작성 탐지 (2026-07-10, US 교차수용 — 삼성 오진 사건의 판별법).
    원리: 오늘 행의 ntm_90d는 '90일 전 시점의 NTM'이므로, ~30일 전 행의 ntm_60d와
    같은 시점을 가리킴 → 일치하면 실제 사건(어닝 base effect), 불일치하면 벤더가
    이력을 재작성한 것(319660.KQ 유형 오염). ★경보 전용 — 자동 덮어쓰기 금지
    (US _robust_n90_map 가드가 정상값을 덮어써 오작동한 교훈).
    returns: [(ticker, 오늘90d, 과거행60d, 괴리%)] 오염 의심 목록."""
    import sqlite3
    from datetime import datetime, timedelta
    con = sqlite3.connect(db_path)
    try:
        # ★정확히 30일(달력) 정렬만 사용 — ±k일 창은 어닝 계단 근처에서
        #   가짜 양성 생성(1차 버전에서 삼성 오검출 33종목 확인). 과거 행 없으면 그날은 스킵.
        ref = (datetime.strptime(today_str, '%Y-%m-%d') - timedelta(days=30))
        past = ref.strftime('%Y-%m-%d')
        exists = con.execute("SELECT 1 FROM ntm_screening WHERE date=? LIMIT 1", (past,)).fetchone()
        if not exists:
            return []
        cur = {r[0]: r[1] for r in con.execute(
            "SELECT ticker, ntm_90d FROM ntm_screening WHERE date=? AND ntm_90d IS NOT NULL", (today_str,))}
        old = {r[0]: r[1] for r in con.execute(
            "SELECT ticker, ntm_60d FROM ntm_screening WHERE date=? AND ntm_60d IS NOT NULL", (past,))}
        out = []
        for t, v90 in cur.items():
            v60 = old.get(t)
            if v60 is None or v60 == 0:
                continue
            gap = abs(v90 / v60 - 1)
            if gap > tol:
                out.append((t, round(v90, 2), round(v60, 2), round(gap * 100, 1)))
        return sorted(out, key=lambda x: -x[3])
    finally:
        con.close()
