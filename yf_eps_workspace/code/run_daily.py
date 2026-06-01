# -*- coding: utf-8 -*-
"""[DEPRECATED 2026-06-01] KR EPS Momentum — Minimal Daily Runner (v1, 200줄)

⚠️ 이 파일은 폐기됨. v2 (`C:/dev/kr_eps_momentum/daily_runner.py`, 5,178줄 US 완전 모방)이
GHA workflow에서 사용 중.

이 파일이 만들어진 이유:
- 2026-06-01 (사용자 화났을 때) 5/14 PoC가 17일 멈춤 상태에서 긴급 복구용으로 만듦
- US와 다른 minimal 200줄 — 메시지 형식이 US와 안 맞아서 사용자가 거부
- "전부 모방" 결정 후 daily_runner.py로 전환

backup으로 유지. GHA workflow에서는 안 호출됨.

이전 흐름: probe (yfinance) → score (NTM) → telegram (개인봇)
이전 위치: 모두 workspace 상대경로. config는 env var.

이전 실행:
  로컬: python yf_eps_workspace/code/run_daily.py [--date YYYYMMDD]
  GHA: (구) kr_eps_daily.yml — 6/1 변경됨

환경변수 (GHA secrets):
  TELEGRAM_BOT_TOKEN  : 봇 토큰
  TELEGRAM_PRIVATE_ID : 개인봇 chat_id (채널 X)

의존: yfinance, pandas, numpy, pyarrow, requests
"""
import sys, os, time, json, argparse
from pathlib import Path
from datetime import datetime
sys.stdout.reconfigure(encoding='utf-8')

import yfinance as yf
import pandas as pd
import numpy as np
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# 경로 — workspace 상대
HERE = Path(__file__).resolve().parent
WS = HERE.parent
UNIVERSE_FILE = WS / 'universe_kr.parquet'
CACHE_DIR = WS / 'data_cache_yf'
LOGS_DIR = WS / 'logs' / 'daily'
CACHE_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# 같은 폴더 import
sys.path.insert(0, str(HERE))
from eps_momentum_system import calculate_ntm_score, get_trend_lights

# config — env var 우선, fallback config.py
def get_telegram_config():
    tok = os.environ.get('TELEGRAM_BOT_TOKEN')
    pid = os.environ.get('TELEGRAM_PRIVATE_ID')
    if tok and pid:
        return tok, pid
    # local fallback
    try:
        sys.path.insert(0, str(WS.parent))  # C:/dev
        from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID
        return TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID
    except Exception:
        return None, None

# 종목명 캐시 (로컬은 data_cache, GHA는 없을 수 있음 → ticker로 fallback)
TICKER_NAMES = {}
for nm_path in [WS.parent / 'data_cache' / 'ticker_names_cache.json',
                WS / 'ticker_names_cache.json']:
    if nm_path.exists():
        try:
            TICKER_NAMES = json.loads(nm_path.read_text(encoding='utf-8'))
            break
        except Exception:
            pass

def get_name(t):
    return TICKER_NAMES.get(t, t)

# ─── 1) Universe ───
def get_universe():
    if not UNIVERSE_FILE.exists():
        print(f'ERROR: {UNIVERSE_FILE} 없음 (universe_kr.parquet)'); sys.exit(1)
    df = pd.read_parquet(UNIVERSE_FILE)
    return [{'code': str(r['code']).zfill(6), 'mc_krw': float(r['mc_krw'])} for _, r in df.iterrows()]

# ─── 2) Probe (yfinance) ───
WORKERS = 3
SLEEP = 0.4

def try_market(code):
    for mkt in ['KS', 'KQ']:
        sym = f'{code}.{mkt}'
        try:
            t = yf.Ticker(sym)
            et = t.eps_trend
            if et is not None and len(et) > 0:
                return sym, mkt, t
        except Exception:
            continue
        time.sleep(0.1)
    return f'{code}.KS', '?', None

def probe(item):
    code = item['code']
    sym, mkt, t_probe = try_market(code)
    r = {
        'ticker': code, 'symbol': sym, 'market': mkt, 'mc_krw': item['mc_krw'],
        'eps_trend_ok': False, 'fy_complete_0y': False,
        '0y_current': np.nan, '0y_7d': np.nan, '0y_30d': np.nan, '0y_60d': np.nan, '0y_90d': np.nan,
        '1y_current': np.nan, '1y_90d': np.nan,
        'up7': np.nan, 'up30': np.nan, 'dn30': np.nan, 'dn7': np.nan,
        'na': np.nan, 'fwd_pe': np.nan, 'fwd_eps': np.nan, 'op_margin': np.nan,
    }
    try:
        t = t_probe if t_probe is not None else yf.Ticker(sym)
        try:
            et = t.eps_trend
            if et is not None and len(et) > 0:
                r['eps_trend_ok'] = True
                if '0y' in et.index:
                    not_nan = 0
                    for c, k in [('current','current'), ('7daysAgo','7d'), ('30daysAgo','30d'),
                                 ('60daysAgo','60d'), ('90daysAgo','90d')]:
                        if c in et.columns:
                            v = et.loc['0y', c]
                            if not pd.isna(v):
                                r[f'0y_{k}'] = float(v); not_nan += 1
                    r['fy_complete_0y'] = (not_nan == 5)
                if '+1y' in et.index:
                    if 'current' in et.columns:
                        v = et.loc['+1y', 'current']
                        if not pd.isna(v): r['1y_current'] = float(v)
                    if '90daysAgo' in et.columns:
                        v = et.loc['+1y', '90daysAgo']
                        if not pd.isna(v): r['1y_90d'] = float(v)
        except Exception: pass
        try:
            er = t.eps_revisions
            if er is not None and len(er) > 0 and '0y' in er.index:
                row = er.loc['0y']
                up30 = row.get('upLast30days')
                if up30 is not None and not pd.isna(up30):
                    r['up7'] = int(row.get('upLast7days') or 0)
                    r['up30'] = int(up30)
                    r['dn30'] = int(row.get('downLast30days') or 0)
                    r['dn7'] = int(row.get('downLast7Days') or 0)
        except Exception: pass
        try:
            info = t.info
            r['na'] = info.get('numberOfAnalystOpinions')
            r['fwd_pe'] = info.get('forwardPE')
            r['fwd_eps'] = info.get('forwardEps')
            r['op_margin'] = info.get('operatingMargins')
        except Exception: pass
    except Exception: pass
    time.sleep(SLEEP)
    return r

def run_probe(date_str):
    out_file = CACHE_DIR / f'kr_yf_{date_str}.parquet'
    if out_file.exists():
        print(f'이미 존재: {out_file.name}, 재사용')
        return pd.read_parquet(out_file)
    t0 = time.time()
    universe = get_universe()
    print(f'  universe: {len(universe)} 종목, workers={WORKERS}, sleep={SLEEP}s', flush=True)
    print(f'  예상: ~{len(universe) * (SLEEP+0.2) / WORKERS / 60:.0f}분', flush=True)
    results = []; n = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(probe, u): u for u in universe}
        for fut in as_completed(futures):
            results.append(fut.result()); n += 1
            if n % 100 == 0 or n == len(universe):
                ok = sum(1 for x in results if x['fy_complete_0y'])
                el = (time.time() - t0) / 60
                print(f'  [{n}/{len(universe)}] fy_complete {ok} — {el:.1f}분', flush=True)
    df = pd.DataFrame(results); df['date'] = date_str
    df = df.sort_values('mc_krw', ascending=False)
    for c in ['fwd_pe','fwd_eps','op_margin','0y_current','0y_7d','0y_30d','0y_60d','0y_90d','1y_current','1y_90d']:
        if c in df.columns: df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.replace([np.inf, -np.inf], np.nan)
    df.to_parquet(out_file, index=False)
    el = (time.time() - t0) / 60
    print(f'  저장: {out_file.name} ({len(df)}종목, fy_ok {df.fy_complete_0y.sum()}, 소요 {el:.1f}분)')
    return df

# ─── 3) Score (NTM) ───
def compute_score(row):
    if not row.get('fy_complete_0y'): return None
    ntm = {'current': row['0y_current'], '7d': row['0y_7d'], '30d': row['0y_30d'],
           '60d': row['0y_60d'], '90d': row['0y_90d']}
    if any(pd.isna(v) for v in ntm.values()): return None
    try:
        score, s1, s2, s3, s4, is_tr, adj, dir_ = calculate_ntm_score(ntm)
        return dict(score=score, adj_score=adj, direction=dir_, s1=s1, s2=s2, s3=s3, s4=s4,
                    is_turnaround=is_tr, min_seg=min(s1,s2,s3,s4))
    except Exception:
        return None

# ─── 4) Message + Telegram ───
def build_message(date_str, df_scored, n_total, n_fy):
    L = []
    L.append(f'🔬 <b>KR EPS Momentum</b> · {date_str}')
    L.append(f'<i>📝 PoC paper trade — 매매 결정 X, 신호 누적 검증 단계</i>')
    L.append('')
    L.append(f'유니버스: {n_total}종목 / fy_complete: {n_fy} ({n_fy/n_total*100:.0f}%)')
    L.append('')
    # min_seg ≥ 0 (전구간 양수) 필터 + adj_score Top 10
    cand = df_scored[df_scored['min_seg'] >= 0].copy()
    cand = cand.sort_values('adj_score', ascending=False).head(10)
    if len(cand) == 0:
        L.append('  • 오늘 min_seg≥0 + 양의 모멘텀 후보 없음')
    else:
        L.append(f'<b>Top {len(cand)} (min_seg≥0, adj_score 내림차순)</b>')
        for i, r in enumerate(cand.itertuples(), 1):
            nm = get_name(r.ticker)
            lights = get_trend_lights(r.s1, r.s2, r.s3, r.s4)
            mc_jo = r.mc_krw / 1e12
            L.append(f'  {i}. <b>{nm}</b>({r.ticker}) · {mc_jo:.1f}조')
            L.append(f'      adj {r.adj_score:+.1f} / dir {r.direction:+.1f} {lights}')
            L.append(f'      90d→7d: {r.s4:+.1f}% {r.s3:+.1f}% {r.s2:+.1f}% {r.s1:+.1f}%')
    L.append('')
    L.append(f'<i>※ paper trade 단계. 자본 X. 5/14 시작 ~ 8월 60일 누적 후 BT 검증.</i>')
    return '\n'.join(L)

def send_telegram(msg, token, pid):
    if not token or not pid:
        print('SKIP telegram: TELEGRAM_BOT_TOKEN/PRIVATE_ID 없음')
        return False
    r = requests.post(f'https://api.telegram.org/bot{token}/sendMessage',
                      data={'chat_id': pid, 'text': msg, 'parse_mode': 'HTML'}, timeout=30)
    j = r.json()
    ok = j.get('ok', False)
    print(f'  [텔레그램] status={r.status_code} ok={ok}')
    if not ok: print(f'    error: {j}')
    return ok

# ─── Main ───
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', default=None, help='YYYYMMDD (default: today KST)')
    ap.add_argument('--no-send', action='store_true', help='메시지만 출력, 발송 X')
    args = ap.parse_args()
    # KST 기준 날짜 (GHA UTC → KST 변환)
    from datetime import timezone, timedelta
    KST = timezone(timedelta(hours=9))
    date_str = args.date or datetime.now(KST).strftime('%Y%m%d')
    print(f'=== KR EPS Daily Runner — {date_str} (KST) ===', flush=True)
    print()
    # 1) probe
    print('[1/3] yfinance probe...')
    df = run_probe(date_str)
    n_total = len(df); n_fy = int(df.fy_complete_0y.sum())
    # 2) score
    print('\n[2/3] NTM score 계산...')
    scores = df.apply(lambda r: compute_score(r) if r.fy_complete_0y else None, axis=1)
    df_scored = df.copy()
    for k in ['score','adj_score','direction','s1','s2','s3','s4','is_turnaround','min_seg']:
        df_scored[k] = scores.apply(lambda x: x[k] if x else np.nan)
    df_scored = df_scored.dropna(subset=['adj_score'])
    print(f'  scored: {len(df_scored)} 종목')
    # 3) message + send
    print('\n[3/3] 메시지 빌드 + 발송...')
    msg = build_message(date_str, df_scored, n_total, n_fy)
    print('─'*60); print(msg); print('─'*60)
    if not args.no_send:
        tok, pid = get_telegram_config()
        send_telegram(msg, tok, pid)
    print(f'\n=== 완료 ({date_str}) ===')

if __name__ == '__main__':
    main()
