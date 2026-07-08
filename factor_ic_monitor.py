# -*- coding: utf-8 -*-
"""팩터별 rolling IC 알파 부식 모니터 (2026-07-09) — 표시 전용, 매매 무관.

목적: 핵심 팩터(G growth_s 0.55 등)의 예측력이 서서히 죽는 걸 라이브에서 조기 감지
(지금은 사후 BT로만 발견 가능). alphalens 방식(rank-IC) 적용.

데이터: state/ranking_*.json (일별 boost 랭킹, 종목별 value_s/growth_s/momentum_s/
mom_10_z/vol_low_z/score 저장) + data_cache/all_ohlcv_adj_*.parquet(최신 glob, 가격).

방법: 날짜 D의 팩터값 vs (D → D+20영업일) 수익률의 Spearman rank-IC.
결과를 state/factor_ic_log.csv에 append-only 누적(date,factor,ic,n) — 증분(이미 기록된
date는 스킵). D+20영업일 가격이 아직 없는 최근 날짜는 자연히 스킵(다음 실행에 처리).

build_health_line(): 팩터별 최근 60일 IC 평균(rolling)을 "60일 rolling IC 평균의 역사
분포" 내 백분위로 비교 — 하위 10% 미만 ⚠️, 5% 미만 🚨. 평시엔 핵심 팩터(V/G/M) 값 요약.

킬스위치: FACTOR_IC_DISABLE=1. 실패 시 빈 문자열(안전, breadth_diagnostic과 동일 패턴).
CLI: python factor_ic_monitor.py --backfill (전체 히스토리 1회 백필) / --line (표본 출력)
"""
import csv
import glob
import os
import re
import sys

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(BASE_DIR, 'state')
DATA_CACHE = os.path.join(BASE_DIR, 'data_cache')
LOG_PATH = os.path.join(STATE_DIR, 'factor_ic_log.csv')

# 핵심 팩터만 (score = V*0.15 + G*0.55 + M*0.30 + mom_10_z*0.05 + vol_low_z*0.06,
# boost Q=0 이라 quality_s 제외). '높을수록 좋다' 부호 통일(value_s도 z-score상 높을수록 저평가/유리).
FACTORS = ['value_s', 'growth_s', 'momentum_s', 'mom_10_z', 'vol_low_z', 'score']
ABBR = {'value_s': 'V', 'growth_s': 'G', 'momentum_s': 'M',
        'mom_10_z': 'mom10', 'vol_low_z': 'vol', 'score': '종합'}
NAME_KR = {'value_s': '밸류', 'growth_s': '성장', 'momentum_s': '모멘텀',
           'mom_10_z': '단기모멘텀', 'vol_low_z': '저변동성', 'score': '종합점수'}

HORIZON = 20       # forward trading days
MIN_N = 10         # 일별 최소 유효 종목수 (미만이면 그날 스킵)
START_DATE = '20190101'  # CLAUDE.md 7.4년 측정기준과 정합 (2018 파일은 mom_10_z 등 미보유)
ROLL_WINDOW = 60
ROLL_MIN_PERIODS = 40
HIST_MIN_POINTS = 30   # 백분위 비교에 필요한 최소 rolling 시계열 길이
WARN_PCT = 0.10
ALERT_PCT = 0.05

_RANKING_RE = re.compile(r'ranking_(\d{8})\.json$')


def _disabled():
    return os.environ.get('FACTOR_IC_DISABLE') == '1'


def _ranking_files():
    """state/ranking_*.json (boost) → [(date_str, path), ...] date 오름차순."""
    out = []
    for f in glob.glob(os.path.join(STATE_DIR, 'ranking_*.json')):
        m = _RANKING_RE.search(os.path.basename(f))
        if m:
            out.append((m.group(1), f))
    out.sort(key=lambda x: x[0])
    return out


def _price_matrix():
    """최신 all_ohlcv_adj_*.parquet → (parr, pcol, tdays, tdi). 영업일만(주말 캘린더 행 제거)."""
    cands = sorted(glob.glob(os.path.join(DATA_CACHE, 'all_ohlcv_adj_*.parquet')))
    if not cands:
        raise FileNotFoundError('all_ohlcv_adj_*.parquet 없음')
    px = pd.read_parquet(cands[-1]).replace(0, np.nan)
    px = px[px.notna().any(axis=1)]  # 캘린더 인덱스 → 영업일만
    pcol = {c: i for i, c in enumerate(px.columns)}
    parr = px.values
    tdays = [d.strftime('%Y%m%d') for d in px.index]
    tdi = {d: i for i, d in enumerate(tdays)}
    return parr, pcol, tdays, tdi


def _existing_dates():
    if not os.path.exists(LOG_PATH):
        return set()
    try:
        df = pd.read_csv(LOG_PATH, dtype={'date': str})
        return set(df['date'].unique())
    except Exception:
        return set()


def update_ic_log(verbose=False):
    """증분 갱신: 아직 로그에 없고 D+20영업일 가격이 확보된 날짜만 계산해 append.
    반환: 신규로 기록한 date 수."""
    if _disabled():
        return 0
    files = _ranking_files()
    files = [(d, f) for d, f in files if d >= START_DATE]
    if not files:
        return 0
    done = _existing_dates()
    parr, pcol, tdays, tdi = _price_matrix()
    n_tdays = len(tdays)

    new_rows = []
    processed = 0
    for d8, path in files:
        if d8 in done:
            continue
        if d8 not in tdi:
            continue  # 랭킹 날짜가 가격 인덱스에 없음(휴장일 mismatch 등) — 스킵
        i0 = tdi[d8]
        i1 = i0 + HORIZON
        if i1 >= n_tdays:
            continue  # 아직 D+20영업일 가격 없음 — 다음 실행에 처리
        try:
            with open(path, encoding='utf-8') as f:
                import json
                d = json.load(f)
            rankings = d.get('rankings') or []
        except Exception:
            continue
        if len(rankings) < MIN_N:
            continue

        rows = []
        for item in rankings:
            t = str(item.get('ticker', '')).zfill(6)
            rows.append({'ticker': t, **{c: item.get(c) for c in FACTORS}})
        rdf = pd.DataFrame(rows)
        if rdf.empty:
            continue

        # forward return (벡터화)
        cols_idx = []
        valid_tk = []
        for t in rdf['ticker']:
            ci = pcol.get(t)
            if ci is not None:
                cols_idx.append(ci)
                valid_tk.append(t)
        if len(valid_tk) < MIN_N:
            continue
        p0 = parr[i0, cols_idx]
        p1 = parr[i1, cols_idx]
        with np.errstate(invalid='ignore', divide='ignore'):
            ret = np.where((p0 > 0) & (p1 > 0), p1 / p0 - 1.0, np.nan)
        fwd_map = dict(zip(valid_tk, ret))
        rdf['fwd'] = rdf['ticker'].map(fwd_map)

        for factor in FACTORS:
            if factor not in rdf.columns:
                continue
            sub = rdf[[factor, 'fwd']].apply(pd.to_numeric, errors='coerce').dropna()
            if len(sub) < MIN_N:
                continue
            ic = sub[factor].corr(sub['fwd'], method='spearman')
            if ic is None or not np.isfinite(ic):
                continue
            new_rows.append({'date': d8, 'factor': factor, 'ic': round(float(ic), 6),
                              'n': len(sub)})
        processed += 1
        if verbose and processed % 200 == 0:
            print(f'  ... {processed}일 처리 (최근 {d8})')

    if new_rows:
        new_file = not os.path.exists(LOG_PATH)
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(LOG_PATH, 'a', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=['date', 'factor', 'ic', 'n'])
            if new_file:
                w.writeheader()
            for r in new_rows:
                w.writerow(r)

    n_dates = len({r['date'] for r in new_rows})
    if verbose:
        print(f'[factor_ic_monitor] 신규 {n_dates}일 기록 ({len(new_rows)}행)')
    return n_dates


def _load_wide():
    """factor_ic_log.csv → date x factor 피벗 (ic). 없으면 None."""
    if not os.path.exists(LOG_PATH):
        return None
    try:
        df = pd.read_csv(LOG_PATH, dtype={'date': str})
        if df.empty:
            return None
        wide = df.pivot_table(index='date', columns='factor', values='ic', aggfunc='last')
        wide = wide.sort_index()
        return wide
    except Exception:
        return None


def factor_health():
    """팩터별 {factor: {'current': 최근60일평균IC, 'pct': 역사백분위(0~1), 'status': ok/warn/alert}}.
    데이터 부족한 팩터는 dict에서 제외."""
    wide = _load_wide()
    if wide is None:
        return {}
    out = {}
    for factor in FACTORS:
        if factor not in wide.columns:
            continue
        s = wide[factor].dropna()
        if len(s) < ROLL_MIN_PERIODS:
            continue
        roll = s.rolling(ROLL_WINDOW, min_periods=ROLL_MIN_PERIODS).mean().dropna()
        if len(roll) < HIST_MIN_POINTS:
            continue
        current = float(roll.iloc[-1])
        hist = roll.values
        pct = float((hist <= current).mean())
        if pct < ALERT_PCT:
            status = 'alert'
        elif pct < WARN_PCT:
            status = 'warn'
        else:
            status = 'ok'
        out[factor] = {'current': current, 'pct': pct, 'status': status, 'n_hist': len(roll)}
    return out


def build_health_line():
    """검문소용 문구. 이상 팩터 있으면 ⚠️/🚨 라인, 없으면 핵심 팩터 요약 1줄.
    데이터 부족/실패 시 빈 문자열(안전, 매매 무영향)."""
    if _disabled():
        return ''
    try:
        health = factor_health()
        if not health:
            return ''
        warn_lines = []
        for factor, h in health.items():
            if h['status'] in ('warn', 'alert'):
                icon = '🚨' if h['status'] == 'alert' else '⚠️'
                warn_lines.append(
                    f"{icon} {NAME_KR.get(factor, factor)} 예측력 저하 "
                    f"(60일IC {h['current']:+.3f}, 역사 하위 {h['pct']*100:.0f}%)")
        if warn_lines:
            return '팩터 건강: ' + ' / '.join(warn_lines)
        parts = []
        for factor in ['value_s', 'growth_s', 'momentum_s']:
            if factor in health:
                parts.append(f"{ABBR[factor]} {health[factor]['current']:+.2f}")
        if not parts:
            return ''
        return f"팩터 건강: {' '.join(parts)} ✅ (60일 IC, 역사 분위 정상)"
    except Exception:
        return ''


def build_ic_line():
    """하위호환 별칭."""
    return build_health_line()


if __name__ == '__main__':
    import argparse
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    ap = argparse.ArgumentParser(description='팩터별 rolling IC 알파 부식 모니터')
    ap.add_argument('--backfill', action='store_true', help='전체 히스토리 1회 백필(증분과 동일 함수)')
    ap.add_argument('--line', action='store_true', help='build_health_line() 표본 출력')
    args = ap.parse_args()

    if args.backfill:
        n = update_ic_log(verbose=True)
        print(f'\n백필 완료: 신규 {n}일')

    if args.backfill or (not args.line):
        wide = _load_wide()
        if wide is not None:
            print(f'\n[factor_ic_log 통계] 총 {len(wide)}일 (기간 {wide.index.min()} ~ {wide.index.max()})')
            for factor in FACTORS:
                if factor in wide.columns:
                    s = wide[factor].dropna()
                    if len(s):
                        print(f'  {NAME_KR.get(factor, factor):<8} 평균IC={s.mean():+.4f}  '
                              f'양수비율={ (s > 0).mean()*100:.0f}%  n일={len(s)}')

    if args.line or args.backfill:
        print('\n[build_health_line 표본]')
        print(' ', build_health_line() or '(빈 문자열)')

    if not (args.backfill or args.line):
        ap.print_help()
