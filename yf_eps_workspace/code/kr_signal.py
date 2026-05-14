"""KR EPS Signal — yf parquet → score 계산 → 매수 후보 메시지

US `eps_momentum_system.calculate_ntm_score` 그대로 활용 (종목 무관).
NTM = 0y current/7d/30d/60d/90d (5스냅샷, endDate 가중 블렌딩 생략 — 0y가중치 ~80%로 근사 충분)

production 무변경. yf_eps_workspace 격리.
"""
import sys, json
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd
import numpy as np
import requests, time
from datetime import datetime
from pathlib import Path

# US core 함수 import (종목 무관)
sys.path.insert(0, r'C:/dev/kr_eps_momentum')
from eps_momentum_system import calculate_ntm_score, get_trend_lights

# v80.6 봇 토큰 (개인봇만)
sys.path.insert(0, r'C:/dev')
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID

WS = Path(r'C:/dev/yf_eps_workspace')
YF_CACHE = WS / 'data_cache_yf'
TICKER_NAMES_FILE = Path(r'C:/dev/data_cache/ticker_names_cache.json')

# 종목명 캐시
with open(TICKER_NAMES_FILE, encoding='utf-8') as f:
    TICKER_NAMES = json.load(f)


def get_name(ticker):
    return TICKER_NAMES.get(ticker, ticker)


def get_latest_yf():
    files = sorted(YF_CACHE.glob('kr_yf_*.parquet'))
    if not files:
        return None, None
    latest = files[-1]
    date_str = latest.stem.replace('kr_yf_', '')
    return date_str, pd.read_parquet(latest)


def compute_score_row(row):
    """단일 종목 NTM score 계산 — US calculate_ntm_score 호출"""
    if not row.get('fy_complete_0y'):
        return None
    ntm_values = {
        'current': row['0y_current'],
        '7d': row['0y_7d'],
        '30d': row['0y_30d'],
        '60d': row['0y_60d'],
        '90d': row['0y_90d'],
    }
    if any(pd.isna(v) for v in ntm_values.values()):
        return None
    try:
        score, seg1, seg2, seg3, seg4, is_turnaround, adj_score, direction = calculate_ntm_score(ntm_values)
        return {
            'score': score, 'adj_score': adj_score, 'direction': direction,
            'seg1': seg1, 'seg2': seg2, 'seg3': seg3, 'seg4': seg4,
            'is_turnaround': is_turnaround,
            'min_seg': min(seg1, seg2, seg3, seg4),
        }
    except Exception as e:
        return None


def calc_fwd_pe_chg(row):
    """가중평균 Fwd P/E 변화율 (v80.10 가중치 7d×0.30 + 30d×0.10 + 60d×0.10 + 90d×0.50).
    음수 = 저평가 (EPS 개선 대비 주가 미반영).
    Note: parquet에 price/historical PE 없음 → fwd_pe (현재만)으로 근사.
    실제 fwd_pe_chg는 NTM EPS 변화율의 역수 근사로 대체.
    """
    cur = row['0y_current']
    if pd.isna(cur) or cur == 0:
        return None
    chg = 0
    weights = {'7d': 0.30, '30d': 0.10, '60d': 0.10, '90d': 0.50}
    total_w = 0
    for k, w in weights.items():
        prev = row.get(f'0y_{k}')
        if pd.isna(prev) or prev == 0:
            continue
        # NTM EPS 증가율 = -fwd_pe 변화율 (역수 근사)
        eps_chg = (cur - prev) / abs(prev)
        chg += -eps_chg * w  # 음수면 저평가
        total_w += w
    if total_w < 0.5:
        return None
    return (chg / total_w) * 100


def build_signal_message(date_str, df, day_n, day_target):
    """Signal 메시지 빌드 — US 형식"""
    lines = []
    lines.append(f'🔬 <b>KR EPS Signal</b> · {date_str} · Day {day_n}/{day_target}')
    lines.append('<i>📝 paper trade — 매매 결정 X, 검증 단계</i>')
    lines.append('')

    # 매수 후보 Top 3 (✅ 검증, min_seg≥0, na≥3)
    eligible = df[
        (df['fy_complete_0y']) & (df['na'] >= 3) & (df['score_data'].notna())
    ].copy()
    if len(eligible) == 0:
        lines.append('매수 후보 없음 (모든 종목 필터 탈락)')
        return '\n'.join(lines)

    # adj_score 정렬 (US Part 2 필터 호환)
    eligible = eligible.sort_values('adj_score', ascending=False)
    # min_seg ≥ 0% 필터 (EPS 추세 건강)
    candidates = eligible[eligible['min_seg'] >= 0].head(3)

    lines.append('━━━━━━━━━━━━━━━')
    lines.append(f'🛒 <b>매수 후보 Top {len(candidates)}</b>')
    lines.append('━━━━━━━━━━━━━━━')
    if len(candidates) == 0:
        lines.append('  (min_seg ≥ 0 조건 충족 종목 없음)')
    else:
        for i, (_, r) in enumerate(candidates.iterrows(), 1):
            name = get_name(str(r['ticker']).zfill(6))
            lines.append(f'{i}. <b>{name}</b>({r["ticker"]}) · NTM 점수 {r["adj_score"]:.1f}')
            trend = get_trend_lights(r['seg1'], r['seg2'], r['seg3'], r['seg4'])
            tend = (trend[0] if isinstance(trend, tuple) else trend) if trend else '☁️☁️☁️☁️ 보합'
            lines.append(f'   추세 {tend}')
            mc_jo = r['mc_krw'] / 1e12
            mc_str = f'{mc_jo:.1f}조' if mc_jo >= 1 else f'{r["mc_krw"]/1e8:.0f}억'
            lines.append(f'   시총 {mc_str} · 분석가 {int(r["na"])}명 · 의견 ↑{int(r.get("up30") or 0)}↓{int(r.get("dn30") or 0)}')
            lines.append('')

    # 선정 과정 (퍼널)
    lines.append('━━━━━━━━━━━━━━━')
    lines.append('📋 <b>선정 과정</b>')
    lines.append('━━━━━━━━━━━━━━━')
    n_total = len(df)
    n_fy = df['fy_complete_0y'].sum()
    n_na3 = (df['na'] >= 3).sum()
    n_fy_na3 = ((df['fy_complete_0y']) & (df['na'] >= 3)).sum()
    n_min_seg = len(eligible[eligible['min_seg'] >= 0])
    lines.append(f'📡 1527 종목 (시총 1천억+)')
    lines.append(f'  → FY 5스냅샷 가용 {n_fy} ({n_fy/n_total*100:.0f}%)')
    lines.append(f'  → 분석가 ≥3 통과 {n_fy_na3}')
    lines.append(f'  → min_seg ≥ 0% 통과 {n_min_seg}')
    lines.append(f'  → 매수 후보 Top {len(candidates)}')
    lines.append('')

    # Top 10 Watchlist
    lines.append('━━━━━━━━━━━━━━━')
    lines.append('📊 <b>Watchlist Top 10</b> (adj_score)')
    lines.append('━━━━━━━━━━━━━━━')
    top10 = eligible.head(10)
    for i, (_, r) in enumerate(top10.iterrows(), 1):
        name = get_name(str(r['ticker']).zfill(6))[:14]
        trend = get_trend_lights(r['seg1'], r['seg2'], r['seg3'], r['seg4'])
        tend_icon = ''.join((trend[0] if isinstance(trend, tuple) else trend).split()[0]) if trend else '☁️☁️☁️☁️'
        flag = '✓' if r['min_seg'] >= 0 else ('⚠️' if r['min_seg'] >= -2 else '⛔')
        lines.append(f'{i:>2}. {flag} {name:<14} {r["adj_score"]:>6.1f}점 {tend_icon}')

    lines.append('')
    lines.append('━━━━━━━━━━━━━━━')
    lines.append('<i>※ 추세 아이콘: 🔥폭등 ☀️강세 🌤️상승 ☁️보합 🌧️하락</i>')
    lines.append('<i>※ 점수 = adj_score (4개 세그먼트 합 × 방향 보정)</i>')
    lines.append(f'<i>※ {date_str} 데이터 · 60일 누적 후 BT 검증 예정</i>')

    return '\n'.join(lines)


def send_telegram(text):
    """v80.6 봇 → PRIVATE_ID 발송 (채널 X)"""
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    chunks = []
    while text:
        if len(text) <= 4000:
            chunks.append(text); break
        split = text.rfind('\n', 0, 4000)
        if split == -1: split = 4000
        chunks.append(text[:split])
        text = text[split:].lstrip('\n')
    results = []
    for chunk in chunks:
        try:
            r = requests.post(url, data={
                'chat_id': TELEGRAM_PRIVATE_ID,
                'text': chunk,
                'parse_mode': 'HTML',
            }, timeout=30)
            results.append(r.ok)
            if not r.ok:
                print(f'발송 실패: {r.status_code} {r.text[:200]}')
        except Exception as e:
            print(f'발송 에러: {e}')
            results.append(False)
        time.sleep(0.5)
    return all(results)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    yf_date, df = get_latest_yf()
    if df is None:
        print('yf data 없음')
        return
    df['ticker'] = df['ticker'].astype(str).str.zfill(6)

    # score 계산 (각 종목)
    print(f'score 계산 중... ({len(df)}종목)')
    score_data = df.apply(compute_score_row, axis=1)
    df['score_data'] = score_data
    # score_data가 dict인 row를 분해
    df['score'] = df['score_data'].apply(lambda x: x['score'] if x else None)
    df['adj_score'] = df['score_data'].apply(lambda x: x['adj_score'] if x else None)
    df['min_seg'] = df['score_data'].apply(lambda x: x['min_seg'] if x else None)
    df['seg1'] = df['score_data'].apply(lambda x: x['seg1'] if x else None)
    df['seg2'] = df['score_data'].apply(lambda x: x['seg2'] if x else None)
    df['seg3'] = df['score_data'].apply(lambda x: x['seg3'] if x else None)
    df['seg4'] = df['score_data'].apply(lambda x: x['seg4'] if x else None)

    n_score = df['score'].notna().sum()
    print(f'  score 산출: {n_score}/{len(df)}')

    # 누적 진행
    day_n = len(list(YF_CACHE.glob('kr_yf_*.parquet')))
    day_target = 60

    msg = build_signal_message(yf_date, df, day_n, day_target)
    print('=' * 60)
    print(msg)
    print('=' * 60)
    print(f'\n메시지 길이: {len(msg)}자')

    if args.dry_run:
        print('\n[dry-run] 발송 안 함')
        return

    print('\n개인봇 발송 중...')
    ok = send_telegram(msg)
    print(f'발송: {"✓ 성공" if ok else "✗ 실패"}')


if __name__ == '__main__':
    main()
