"""v41 메시지 Quick Test — ranking JSON에서 데이터 로드 후 3개 메시지 생성

Signal + AI Risk + Watchlist (v41 구조)
"""
import sys
import io
import json
import re
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from send_telegram_auto import (
    get_korea_now, get_recent_trading_dates, KST,
    create_signal_message, create_ai_risk_message, create_watchlist_message,
    send_telegram_long, _get_buy_rationale,
)
from ranking_manager import (
    load_recent_rankings, get_stock_status, get_daily_changes,
)
from credit_monitor import format_credit_compact
from config import TELEGRAM_BOT_TOKEN

# stdout UTF-8 설정 (import 이후 — send_telegram_auto가 먼저 설정)
if not isinstance(sys.stdout, io.TextIOWrapper) or sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def load_latest_rankings():
    """state/ 디렉토리에서 최신 3개 ranking JSON 로드"""
    state_dir = Path(__file__).parent / 'state'
    files = sorted(state_dir.glob('ranking_*.json'), reverse=True)

    dates = []
    for f in files:
        d = f.stem.replace('ranking_', '')
        if len(d) == 8 and d.isdigit():
            dates.append(d)

    if not dates:
        print("ranking JSON 파일이 없습니다.")
        return None, None, None, []

    trading_dates = dates[:3]
    print(f"사용 날짜: {trading_dates}")

    ranking_data = load_recent_rankings(trading_dates)
    rankings_t0 = ranking_data.get(trading_dates[0])
    rankings_t1 = ranking_data.get(trading_dates[1]) if len(trading_dates) >= 2 else None
    rankings_t2 = ranking_data.get(trading_dates[2]) if len(trading_dates) >= 3 else None

    return rankings_t0, rankings_t1, rankings_t2, trading_dates


def mock_credit():
    """mock 시장 위험 지표"""
    return {
        'hy': {
            'hy_spread': 2.88, 'median_10y': 3.79, 'hy_3m_ago': 3.02,
            'hy_prev': 2.90,
            'quadrant': 'Q2', 'quadrant_label': '여름(성장국면)',
            'quadrant_icon': '☀️', 'q_days': 35,
            'signals': [], 'action': '평소대로 투자하세요.',
        },
        'kr': {
            'spread': 2.85, 'spread_prev': 2.83,
            'median_5y': 3.12, 'spread_3m_ago': 2.95,
            'regime': 'normal', 'regime_label': '정상', 'regime_icon': '🟢',
            'ktb_3y': 2.82, 'bbb_rate': 5.67,
        },
        'vix': {
            'vix_current': 20.2, 'vix_5d_ago': 19.8,
            'vix_slope': 0.4, 'vix_slope_dir': 'flat',
            'vix_ma_20': 19.5, 'vix_pct': 55,
            'regime': 'normal', 'regime_label': '안정', 'regime_icon': '🟢',
            'cash_adjustment': 0, 'direction': 'stable',
        },
        'concordance': 'both_stable',
        'final_action': '모든 지표가 안정적이에요. 평소대로 투자하세요.',
    }


def mock_narratives(picks):
    """mock AI 내러티브"""
    templates = {
        '000660': 'HBM 수요 폭증으로 매출 +23%. Fwd PER 5.8로 성장 대비 저평가.',
        '402340': 'AI 반도체 자회사 가치 재평가. 지주사 할인 축소 중이에요.',
        '089970': '클라우드 보안 수요 급증으로 매출 +35%. 수익성도 개선 중이에요.',
        '095610': '반도체 장비 수주 호조. 국내외 팹 투자 확대 수혜주예요.',
        '119850': 'LNG 사업 안정 수익에 신재생에너지 수주까지. 배당수익률 3.2%도 매력.',
    }
    result = {}
    for p in picks:
        t = p['ticker']
        if t in templates:
            result[t] = templates[t]
        else:
            result[t] = _get_buy_rationale(p)
    return result


def main():
    print("=" * 50)
    print("v41 Quick Test — Signal + AI Risk + Watchlist")
    print("=" * 50)

    # 1. 데이터 로드
    rankings_t0, rankings_t1, rankings_t2, trading_dates = load_latest_rankings()
    if not rankings_t0:
        return 1

    BASE_DATE = trading_dates[0]
    biz_day = datetime.strptime(BASE_DATE, '%Y%m%d')
    print(f"기준일: {BASE_DATE}")
    print(f"T-0 종목: {len(rankings_t0.get('rankings', []))}개")

    # 2. 파이프라인 상태
    pipeline = get_stock_status(rankings_t0, rankings_t1, rankings_t2)
    v_count = sum(1 for s in pipeline if s['status'] == '✅')
    d_count = sum(1 for s in pipeline if s['status'] == '⏳')
    n_count = sum(1 for s in pipeline if s['status'] == '🆕')
    print(f"파이프라인: ✅ {v_count} · ⏳ {d_count} · 🆕 {n_count}")

    cold_start = rankings_t1 is None or rankings_t2 is None

    # 3. 일일 변동
    entered, exited = [], []
    if not cold_start and rankings_t1:
        entered, exited = get_daily_changes(pipeline, rankings_t0, rankings_t1)
    print(f"이탈: {len(exited)}개")

    # 4. picks 선정 (✅ 종목 가중순위 상위 5)
    verified = [s for s in pipeline if s['status'] == '✅']
    verified.sort(key=lambda x: x['rank'])
    picks = verified[:5]

    # rank_t0/t1/t2 추가
    t1_map = {r['ticker']: r.get('composite_rank', r['rank']) for r in rankings_t1.get('rankings', [])} if rankings_t1 else {}
    t2_map = {r['ticker']: r.get('composite_rank', r['rank']) for r in rankings_t2.get('rankings', [])} if rankings_t2 else {}
    for p in picks:
        p['rank_t0'] = p.get('composite_rank', p['rank'])
        p['rank_t1'] = t1_map.get(p['ticker'], '-')
        p['rank_t2'] = t2_map.get(p['ticker'], '-')
        p['_tech'] = {'price': p.get('price', 0)}

    print(f"포트폴리오: {len(picks)}종목")

    # 5. Mock data
    credit = mock_credit()
    final_action = credit['final_action']
    ai_narratives = mock_narratives(picks)
    pick_level = {'max_picks': 5, 'label': '정상', 'warning': None}

    # 6. 메시지 생성
    print("\n" + "=" * 50)
    print("=== Message 1: Signal ===")
    print("=" * 50)
    msg_signal = create_signal_message(
        picks, pipeline, exited, biz_day, ai_narratives,
        5, 20, rankings_t0, rankings_t1, rankings_t2,
        cold_start, final_action, pick_level,
    )
    clean = re.sub(r'<[^>]+>', '', msg_signal)
    print(clean)
    print(f"\n[{len(msg_signal)}자]")

    print("\n" + "=" * 50)
    print("=== Message 2: AI Risk ===")
    print("=" * 50)
    mock_ai_text = '\n'.join([
        '📰 시장 동향',
        '코스피는 외국인 순매수에 소폭 상승했어요.',
        '반도체·2차전지 중심으로 강세가 이어졌어요.',
        '',
        '⚠️ 매수 주의',
        'SK하이닉스(000660) RSI 72, 단기 과열 주의',
    ])
    msg_ai_risk = create_ai_risk_message(
        credit,
        (2650.5, 0.82, '🟢'),
        (892.3, -0.45, '🟡'),
        [],
        mock_ai_text,
        biz_day, picks, final_action,
    )
    clean = re.sub(r'<[^>]+>', '', msg_ai_risk)
    print(clean)
    print(f"\n[{len(msg_ai_risk)}자]")

    print("\n" + "=" * 50)
    print("=== Message 3: Watchlist ===")
    print("=" * 50)
    msg_watchlist = create_watchlist_message(
        pipeline, exited, rankings_t0, rankings_t1, rankings_t2,
        cold_start=cold_start, credit=credit,
    )
    clean = re.sub(r'<[^>]+>', '', msg_watchlist)
    print(clean[:2000] + '\n...(truncated)' if len(clean) > 2000 else clean)
    print(f"\n[{len(msg_watchlist)}자]")

    # 7. 텔레그램 발송 여부 확인
    try:
        from config import TELEGRAM_PRIVATE_ID
        private_id = TELEGRAM_PRIVATE_ID
    except (ImportError, AttributeError):
        private_id = None

    if not private_id:
        print("\nTELEGRAM_PRIVATE_ID 미설정 — 텔레그램 전송 불가")
        return 0

    print("\n")
    answer = input("텔레그램으로 전송할까요? (y/n): ").strip().lower()
    if answer == 'y':
        messages = [msg_signal, msg_ai_risk, msg_watchlist]
        labels = ['Signal', 'AI Risk', 'Watchlist']
        for i, msg in enumerate(messages):
            results = send_telegram_long(msg, TELEGRAM_BOT_TOKEN, private_id)
            codes = [str(r.status_code) for r in results]
            print(f"  {labels[i]} 전송: {', '.join(codes)}")
    else:
        print("전송 건너뜀")

    print("\nDone!")
    return 0


if __name__ == '__main__':
    sys.exit(main())
