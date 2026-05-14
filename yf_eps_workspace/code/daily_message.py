"""KR EPS 매일 개인봇 메시지

매일 1회 실행:
  1. paper_trade.py 결과 (v80.6 + yf 매핑 패턴 A/B/C)
  2. KR yf NTM Top 10 (독립 신호)
  3. 누적 진행 (Day N/60+)
  → 개인봇으로 발송 (채널 절대 X)

발송: v80.6 production 봇 토큰 재사용, PRIVATE_ID만 발송.
production 코드 무변경.
"""
import sys, json, time, sqlite3
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd
import numpy as np
import requests
from datetime import datetime
from pathlib import Path

WS = Path(r'C:/dev/yf_eps_workspace')
YF_CACHE = WS / 'data_cache_yf'
DB_PATH = WS / 'paper_trade.db'
TICKER_NAMES_FILE = Path(r'C:/dev/data_cache/ticker_names_cache.json')  # read-only

# 종목명 캐시 (v80.6 production 재사용)
TICKER_NAMES = {}
if TICKER_NAMES_FILE.exists():
    with open(TICKER_NAMES_FILE, encoding='utf-8') as f:
        TICKER_NAMES = json.load(f)


def get_name(ticker):
    return TICKER_NAMES.get(ticker, ticker)

# v80.6 production config 사용 (봇 토큰 + PRIVATE_ID)
sys.path.insert(0, r'C:/dev')
try:
    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID
except ImportError:
    print('ERROR: v80.6 config.py 없음 (TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID)')
    sys.exit(1)


# v80.10b 가중치
NTM_WEIGHTS = {'7d': 0.30, '30d': 0.10, '60d': 0.10, '90d': 0.50}
DAYS_TARGET = 60


def compute_ntm_score(row):
    cur = row.get('0y_current')
    if pd.isna(cur) or cur == 0:
        return np.nan
    score = 0.0
    valid_weight = 0.0
    for k, w in NTM_WEIGHTS.items():
        prev = row.get(f'0y_{k}')
        if pd.isna(prev) or prev == 0:
            continue
        change = (cur - prev) / abs(prev)
        score += w * change
        valid_weight += w
    if valid_weight < 0.5:
        return np.nan
    return score / valid_weight


def get_latest_yf():
    files = sorted(YF_CACHE.glob('kr_yf_*.parquet'))
    if not files:
        return None, None
    latest = files[-1]
    date_str = latest.stem.replace('kr_yf_', '')
    return date_str, pd.read_parquet(latest)


def get_paper_trade_signals(date_str):
    """paper_trade.db에서 해당 일자 신호 추출"""
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql('SELECT * FROM signals WHERE date = ?', conn, params=(date_str,))
    conn.close()
    return df


def get_accumulation_status():
    """누적 진행 상황"""
    parquet_files = sorted(YF_CACHE.glob('kr_yf_*.parquet'))
    n_days = len(parquet_files)
    if n_days == 0:
        return 0, 0
    return n_days, DAYS_TARGET


def build_message(yf_date, yf_df, paper_df, day_n, day_target):
    """텔레그램 메시지 빌드"""
    lines = []
    lines.append(f'🔬 <b>KR EPS Probe — Day {day_n}/{day_target}</b>')
    lines.append(f'<i>{yf_date} · paper trade · 매매 결정 X</i>')
    lines.append('')

    # [1] paper trade 결과 (v80.6 + yf 매핑)
    if paper_df is not None and len(paper_df) > 0:
        lines.append('<b>[1] v80.6 + yf 신호 매핑</b>')

        # 패턴 A: 진입 후보
        a_enter = paper_df[paper_df['pattern_A_signal'] == 'enter']
        a_hold = paper_df[paper_df['pattern_A_signal'] == 'hold_back']
        a_noyf = paper_df[paper_df['pattern_A_signal'] == 'no_yf']

        if len(a_enter) > 0 or len(a_hold) > 0 or len(a_noyf) > 0:
            lines.append('  진입 후보 (v80.6 top):')
            for _, r in a_enter.iterrows():
                ntm = f'NTM {r["ntm_score"]:+.2f}' if r['ntm_score'] is not None else 'NTM N/A'
                lines.append(f'  ✓ {r["ticker"]} {r["name"][:10]} rank={r["v80_rank"]} {ntm} — 양쪽 강세')
            for _, r in a_hold.iterrows():
                ntm = f'NTM {r["ntm_score"]:+.2f}' if r['ntm_score'] is not None else 'NTM N/A'
                lines.append(f'  ⚠️ {r["ticker"]} {r["name"][:10]} rank={r["v80_rank"]} {ntm} — yf 약세')
            for _, r in a_noyf.iterrows():
                lines.append(f'  ? {r["ticker"]} {r["name"][:10]} rank={r["v80_rank"]} — yf 데이터 없음')

        # 패턴 B: 조기 매도
        b_exit = paper_df[paper_df['pattern_B_signal'] == 'exit_early']
        if len(b_exit) > 0:
            lines.append('  ⏰ 조기 매도 신호:')
            for _, r in b_exit.iterrows():
                lines.append(f'  ⛔ {r["ticker"]} {r["name"][:10]} rank={r["v80_rank"]} NTM {r["ntm_score"]:+.2f}')
        else:
            lines.append('  ⏰ 조기 매도 신호: 없음')

        # 패턴 C: Watchlist 격상
        c_promote = paper_df[paper_df['pattern_C_signal'] == 'promote']
        if len(c_promote) > 0:
            lines.append('  ★ Watchlist 격상 후보:')
            for _, r in c_promote.iterrows():
                lines.append(f'  ⬆ {r["ticker"]} {r["name"][:10]} rank={r["v80_rank"]} NTM {r["ntm_score"]:+.2f}')
        else:
            lines.append('  ★ Watchlist 격상: 없음')
    else:
        lines.append('<b>[1] paper trade DB 비어있음</b>')

    lines.append('')

    # [2] KR yf NTM Top 10 (독립 신호)
    if yf_df is not None and len(yf_df) > 0:
        yf_df = yf_df.copy()
        yf_df['ntm_score'] = yf_df.apply(compute_ntm_score, axis=1)
        # fy_complete + na>=3 + ntm_score 유효한 종목만
        valid = yf_df[(yf_df['fy_complete_0y']) & (yf_df['na'] >= 3) & (yf_df['ntm_score'].notna())]
        if len(valid) > 0:
            top10 = valid.sort_values('ntm_score', ascending=False).head(10)
            lines.append('<b>[2] KR yf NTM Top 10 (독립 신호)</b>')
            for i, (_, r) in enumerate(top10.iterrows(), 1):
                name = get_name(str(r['ticker']).zfill(6))[:12]
                mc_jo = r['mc_krw'] / 1e12
                mc_str = f'{mc_jo:.1f}조' if mc_jo >= 1 else f'{r["mc_krw"]/1e8:.0f}억'
                rev_net = (r.get('up30', 0) or 0) - (r.get('dn30', 0) or 0)
                lines.append(f'  {i}. {r["ticker"]} {name:<13} NTM {r["ntm_score"]:+.2f}'
                            f' · {mc_str} · na={int(r["na"])} · rev↑{int(r.get("up30") or 0)}↓{int(r.get("dn30") or 0)}')
        else:
            lines.append('<b>[2] yf NTM 가용 종목 없음</b>')
    else:
        lines.append('<b>[2] yf 데이터 없음</b>')

    lines.append('')

    # [3] 누적 진행
    lines.append(f'<b>[3] 데이터 누적</b>')
    if yf_df is not None:
        et_ok = yf_df['eps_trend_ok'].sum() if 'eps_trend_ok' in yf_df else 0
        fy_ok = yf_df['fy_complete_0y'].sum() if 'fy_complete_0y' in yf_df else 0
        na3 = (yf_df['na'].fillna(0) >= 3).sum() if 'na' in yf_df else 0
        n_total = len(yf_df)
        lines.append(f'  Universe: {n_total}종목 (시총 1천억+)')
        lines.append(f'  fy_complete: {fy_ok} ({fy_ok/n_total*100:.0f}%) · na≥3: {na3} ({na3/n_total*100:.0f}%)')
    lines.append(f'  누적: Day {day_n}/{day_target}')
    lines.append('')
    lines.append('<i>※ 60일 누적 후 paired BT로 alpha 검증 예정</i>')
    lines.append('<i>※ v80.6 production 매매와 무관한 paper trade 기록</i>')

    return '\n'.join(lines)


def send_telegram(text):
    """v80.6 봇 → PRIVATE_ID만 발송 (채널 절대 X)"""
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    # 4000자 제한 분할
    chunks = []
    while text:
        if len(text) <= 4000:
            chunks.append(text); break
        # 줄 단위 분할
        split = text.rfind('\n', 0, 4000)
        if split == -1: split = 4000
        chunks.append(text[:split])
        text = text[split:].lstrip('\n')

    results = []
    for chunk in chunks:
        try:
            r = requests.post(url, data={
                'chat_id': TELEGRAM_PRIVATE_ID,  # 개인봇만, 채널 X
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
    """매일 1회 실행 — 최신 yf data + paper trade 결과로 메시지 생성+발송"""
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', default=None, help='yf data date (default: latest)')
    ap.add_argument('--dry-run', action='store_true', help='발송 안 함, 메시지만 출력')
    args = ap.parse_args()

    # 데이터 로드
    yf_date, yf_df = get_latest_yf()
    if yf_date is None:
        print('yf 데이터 없음 — daily_probe 먼저 실행')
        return
    if args.date:
        target_file = YF_CACHE / f'kr_yf_{args.date}.parquet'
        if target_file.exists():
            yf_date = args.date
            yf_df = pd.read_parquet(target_file)

    # paper trade 신호 (v80.6 ranking date는 production state의 최신, paper_trade에 저장된 date)
    paper_df = get_paper_trade_signals(yf_date) if (DB_PATH.exists()) else None
    # fallback: paper_trade는 v80.6 date 기준이라 yf_date와 다를 수 있음 — 최신 paper trade 사용
    if paper_df is None or len(paper_df) == 0:
        conn = sqlite3.connect(DB_PATH)
        latest_paper = pd.read_sql(
            'SELECT date FROM signals ORDER BY date DESC LIMIT 1', conn).iloc[0]['date'] if DB_PATH.exists() else None
        if latest_paper:
            paper_df = pd.read_sql('SELECT * FROM signals WHERE date = ?', conn, params=(latest_paper,))
        conn.close()

    day_n, day_target = get_accumulation_status()

    msg = build_message(yf_date, yf_df, paper_df, day_n, day_target)
    print('=' * 60)
    print(msg)
    print('=' * 60)

    if args.dry_run:
        print('\n[dry-run] 발송 안 함.')
        return

    print('\n개인봇 발송 중...')
    ok = send_telegram(msg)
    print(f'발송: {"✓ 성공" if ok else "✗ 실패"}')


if __name__ == '__main__':
    main()
