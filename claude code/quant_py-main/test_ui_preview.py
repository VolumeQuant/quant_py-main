"""
UI 프리뷰 v8.1 — Guide → [1/3] 시장+Top30 → [2/3] AI 리스크 필터 → [3/3] 최종 추천
가짜 데이터로 전체 메시지 흐름 미리보기
"""
import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

WEIGHT_PER_STOCK = 20

SECTOR_DB = {
    '000270': '자동차', '000660': 'AI반도체/메모리',
    '015760': '전력/유틸리티', '030200': '통신',
}

# ============================================================
# 포맷 함수 (독립 실행용)
# ============================================================

def format_overview(has_ai=False):
    lines = [
        '━━━━━━━━━━━━━━━━━━━',
        '      📖 투자 가이드',
        '━━━━━━━━━━━━━━━━━━━',
        '',
        '🔎 <b>어떤 종목을 찾나요?</b>',
        '국내 전 종목을 매일 자동 분석해서',
        '"좋은 회사를 싸게 살 수 있는 타이밍"을 찾아요.',
        '',
        '📊 <b>어떻게 골라요?</b>',
        '매일 새벽 5단계로 걸러요.',
        '',
        '① 시가총액·재무 건전성으로 1차 스크리닝',
        '② 가치 + 수익성 + 모멘텀 멀티팩터 점수 산출',
        '③ 60일 이동평균선 위 종목만 통과',
        '④ 3거래일 연속 상위 30위 유지 → 검증 완료 ✅',
        '⑤ AI 위험 점검 후 최종 매수 후보 선정',
        '',
        '⏱️ <b>얼마나 보유하나요?</b>',
        'Top 30에 남아있는 동안은 계속 보유하세요.',
        '목록에서 빠지면 매도를 검토하면 돼요.',
        '',
        '📩 <b>오늘의 메시지</b>',
    ]
    if has_ai:
        lines.append('[1/3] 📊 시장 + Top 30')
        lines.append('[2/3] 🛡️ AI 리스크 필터')
        lines.append('[3/3] 🎯 최종 추천')
    else:
        lines.append('📊 시장 + Top 30')
    return '\n'.join(lines)


def _get_buy_rationale(pick):
    reasons = []
    fwd = pick.get('fwd_per')
    per = pick.get('per')
    roe = pick.get('roe')
    tech = pick.get('_tech') or {}
    if fwd and per and fwd < per and per > 0:
        reasons.append(f"실적 개선 (PER {per:.0f}→{fwd:.0f})")
    elif per and per < 10:
        reasons.append(f"저평가 PER {per:.1f}")
    if roe and roe > 15:
        reasons.append(f"ROE {roe:.0f}%")
    rsi = tech.get('rsi')
    if rsi and rsi < 35:
        reasons.append("과매도 구간")
    w52 = tech.get('w52_pct')
    if w52 and w52 < -30:
        reasons.append("52주 저점 부근")
    if not reasons:
        reasons.append("멀티팩터 상위")
    return ' · '.join(reasons[:2])


def format_buy_recommendations(picks, base_date_str, universe_count=0, ai_picks_text=None, skipped=None):
    if not picks:
        return ""
    n = len(picks)
    cash_weight = 100 - n * WEIGHT_PER_STOCK

    if universe_count > 0:
        funnel = f"{universe_count:,}종목 → Top 30 → ✅ 검증 → 최종 {n}종목"
    else:
        funnel = f"Top 30 → ✅ 검증 → 최종 {n}종목"

    lines = [
        "━━━━━━━━━━━━━━━━━━━",
        " [3/3] 🎯 최종 추천",
        "━━━━━━━━━━━━━━━━━━━",
        f"📅 {base_date_str} 기준",
        funnel,
        "",
    ]

    if skipped:
        for candidate, chg in skipped:
            lines.append(f"⚠️ {candidate['name']}(가중 {candidate['weighted_rank']}) 전일 {chg:.1f}% 급락 → 제외")
        lines.append("")

    weight_parts = [f"{p['name']} {WEIGHT_PER_STOCK}%" for p in picks]
    lines.append("📊 <b>비중 한눈에 보기</b>")
    lines.append(' · '.join(weight_parts))
    if cash_weight > 0:
        lines.append(f"현금 {cash_weight}%")
    lines.append("")

    if ai_picks_text:
        lines.append("─────────────────")
        lines.append(ai_picks_text)
        lines.append("─────────────────")
    else:
        lines.append("─────────────────")
        for i, pick in enumerate(picks):
            name = pick['name']
            ticker = pick['ticker']
            sector = SECTOR_DB.get(ticker, '기타')
            rationale = _get_buy_rationale(pick)
            lines.append(f"<b>{i+1}. {name}({ticker}) · {WEIGHT_PER_STOCK}%</b>")
            lines.append(f"{sector} · {rationale}")
            if i < n - 1:
                lines.append("──────────────────")
        lines.append("─────────────────")

    lines.append("")
    lines.append("💡 <b>활용법</b>")
    lines.append("· 비중대로 분산 투자를 권장해요")
    lines.append("· Top 30에서 빠지면 매도 검토")
    lines.append("⚠️ 참고용이며, 투자 판단은 본인 책임이에요.")
    return '\n'.join(lines)


def format_top30(pipeline, exited, cold_start=False, has_next=False, rankings_t0=None, rankings_t1=None, rankings_t2=None, credit=None):
    if not pipeline:
        return ""
    lines = [
        "─────────────────",
        "<b>📋 Top 30 — 보유 확인</b>",
        "─────────────────",
        "목록에 있으면 보유, 없으면 매도 검토.",
        "",
    ]
    verified = [s for s in pipeline if s['status'] == '✅']
    two_day = [s for s in pipeline if s['status'] == '⏳']
    new_stocks = [s for s in pipeline if s['status'] == '🆕']

    if verified and rankings_t1 and rankings_t2:
        t1_map = {r['ticker']: r['rank'] for r in rankings_t1.get('rankings', []) if r['rank'] <= 30}
        t2_map = {r['ticker']: r['rank'] for r in rankings_t2.get('rankings', []) if r['rank'] <= 30}
        for s in verified:
            r0 = s['rank']
            r1 = t1_map.get(s['ticker'], r0)
            r2 = t2_map.get(s['ticker'], r0)
            s['_r1'] = r1
            s['_r2'] = r2
            s['_weighted'] = r0 * 0.5 + r1 * 0.3 + r2 * 0.2
        verified.sort(key=lambda x: x['_weighted'])

    groups_added = False
    if verified:
        if rankings_t1 and rankings_t2:
            names = ', '.join(f"{s['name']}({s['rank']}→{s['_r1']}→{s['_r2']})" for s in verified)
        else:
            names = ', '.join(f"{s['name']}({s['rank']})" for s in verified)
        lines.append(f"✅ 3일 검증: {names}")
        groups_added = True
    if two_day:
        if groups_added:
            lines.append("")
        if rankings_t1:
            t1_map_td = {r['ticker']: r['rank'] for r in rankings_t1.get('rankings', []) if r['rank'] <= 30}
            names = ', '.join(f"{s['name']}({s['rank']}→{t1_map_td.get(s['ticker'], '?')})" for s in two_day)
        else:
            names = ', '.join(f"{s['name']}({s['rank']})" for s in two_day)
        lines.append(f"⏳ 내일 검증: {names}")
        groups_added = True
    if new_stocks:
        if groups_added:
            lines.append("")
        names = ', '.join(f"{s['name']}({s['rank']})" for s in new_stocks)
        lines.append(f"🆕 신규 진입: {names}")

    if exited:
        lines.append("")
        t0_rank_map = {item['ticker']: item['rank'] for item in (rankings_t0 or {}).get('rankings', [])}
        lines.append(f"📉 어제 대비 이탈 {len(exited)}개")
        for e in exited:
            prev = e['rank']
            cur = t0_rank_map.get(e['ticker'])
            reason = e.get('exit_reason', '')
            reason_tag = f" [{reason}]" if reason else ""
            if cur:
                lines.append(f"  {e['name']} {prev}위 → {cur}위{reason_tag}")
            else:
                lines.append(f"  {e['name']} {prev}위 → 순위권 밖{reason_tag}")
        lines.append("⛔ 보유 중이라면 매도를 검토하세요.")

    if cold_start:
        lines.append("")
        lines.append("📊 데이터 축적 중 — 3일 완료 시 매수 후보가 선정돼요.")

    lines.append("")
    if has_next:
        lines.append("👉 다음: AI 리스크 필터 [2/3]")
    return '\n'.join(lines)


# ============================================================
# 가짜 데이터
# ============================================================

fake_picks = [
    {
        'ticker': '000660', 'name': 'SK하이닉스',
        'rank': 1, 'weighted_rank': 1.0,
        'rank_t0': 1, 'rank_t1': 1, 'rank_t2': 1,
        'per': 8.5, 'pbr': 1.3, 'roe': 22.1, 'fwd_per': 6.8,
        '_tech': {'price': 245000, 'daily_chg': 2.31, 'rsi': 38, 'w52_pct': -18},
    },
    {
        'ticker': '032640', 'name': 'LG유플러스',
        'rank': 2, 'weighted_rank': 2.0,
        'rank_t0': 2, 'rank_t1': 2, 'rank_t2': 2,
        'per': 7.3, 'pbr': 0.5, 'roe': 7.8, 'fwd_per': 6.5,
        '_tech': {'price': 13200, 'daily_chg': 0.38, 'rsi': 45, 'w52_pct': -15},
    },
    {
        'ticker': '015760', 'name': '한국전력',
        'rank': 3, 'weighted_rank': 3.2,
        'rank_t0': 3, 'rank_t1': 3, 'rank_t2': 4,
        'per': 5.2, 'pbr': 0.4, 'roe': 8.5, 'fwd_per': 4.1,
        '_tech': {'price': 28750, 'daily_chg': -0.52, 'rsi': 42, 'w52_pct': -25},
    },
    {
        'ticker': '282330', 'name': 'BGF리테일',
        'rank': 4, 'weighted_rank': 4.2,
        'rank_t0': 4, 'rank_t1': 4, 'rank_t2': 5,
        'per': 12.1, 'pbr': 1.8, 'roe': 15.2, 'fwd_per': 10.5,
        '_tech': {'price': 185000, 'daily_chg': 11.5, 'rsi': 68, 'w52_pct': -8},
    },
    {
        'ticker': '023590', 'name': '다우기술',
        'rank': 6, 'weighted_rank': 5.9,
        'rank_t0': 6, 'rank_t1': 5, 'rank_t2': 7,
        'per': 6.8, 'pbr': 0.9, 'roe': 14.5, 'fwd_per': 5.8,
        '_tech': {'price': 32100, 'daily_chg': 1.26, 'rsi': 47, 'w52_pct': -20},
    },
]

fake_pipeline = [
    {'name': 'SK하이닉스', 'rank': 1, 'status': '✅', 'ticker': '000660'},
    {'name': 'LG유플러스', 'rank': 2, 'status': '✅', 'ticker': '032640'},
    {'name': '한국전력', 'rank': 3, 'status': '✅', 'ticker': '015760'},
    {'name': 'BGF리테일', 'rank': 4, 'status': '✅', 'ticker': '282330'},
    {'name': '이엔에프테크놀로지', 'rank': 5, 'status': '✅', 'ticker': '102710'},
    {'name': '다우기술', 'rank': 6, 'status': '✅', 'ticker': '023590'},
    {'name': 'JW중외제약', 'rank': 7, 'status': '✅', 'ticker': '001060'},
    {'name': '제룡전기', 'rank': 8, 'status': '⏳', 'ticker': '033100'},
    {'name': 'HD현대', 'rank': 9, 'status': '✅', 'ticker': '267250'},
    {'name': '삼지전자', 'rank': 10, 'status': '✅', 'ticker': '037460'},
    {'name': 'KT', 'rank': 11, 'status': '✅', 'ticker': '030200'},
    {'name': '삼성전자', 'rank': 12, 'status': '✅', 'ticker': '005930'},
    {'name': 'SK스퀘어', 'rank': 13, 'status': '⏳', 'ticker': '402340'},
    {'name': '기아', 'rank': 14, 'status': '✅', 'ticker': '000270'},
    {'name': '지엔씨에너지', 'rank': 15, 'status': '✅', 'ticker': '119850'},
    {'name': '영원무역', 'rank': 16, 'status': '✅', 'ticker': '111770'},
    {'name': '현대엘리베이터', 'rank': 17, 'status': '✅', 'ticker': '017800'},
    {'name': 'GS', 'rank': 18, 'status': '✅', 'ticker': '078930'},
    {'name': 'KCC', 'rank': 19, 'status': '✅', 'ticker': '002380'},
    {'name': '현대글로비스', 'rank': 20, 'status': '✅', 'ticker': '086280'},
    {'name': '테스', 'rank': 21, 'status': '✅', 'ticker': '095610'},
    {'name': '현대백화점', 'rank': 22, 'status': '✅', 'ticker': '069960'},
    {'name': 'F&F', 'rank': 23, 'status': '✅', 'ticker': '383220'},
    {'name': 'LX인터내셔널', 'rank': 24, 'status': '✅', 'ticker': '001120'},
    {'name': '동성화인텍', 'rank': 25, 'status': '✅', 'ticker': '033500'},
    {'name': '한국타이어앤테크놀로지', 'rank': 26, 'status': '✅', 'ticker': '161390'},
    {'name': '나무가', 'rank': 27, 'status': '⏳', 'ticker': '190510'},
    {'name': '신세계', 'rank': 28, 'status': '⏳', 'ticker': '004170'},
    {'name': 'SK텔레콤', 'rank': 29, 'status': '⏳', 'ticker': '017670'},
    {'name': '코나아이', 'rank': 30, 'status': '🆕', 'ticker': '052400'},
]

fake_exited = [
    {'name': '헥토이노베이션', 'rank': 16, 'ticker': '124500', 'exit_reason': 'M↓'},
]

# 이탈 종목의 현재 순위 + 3일 순위 데이터
fake_rankings_t0 = {
    'rankings': [
        *[{'ticker': s['ticker'], 'rank': s['rank']} for s in fake_pipeline],
    ]
}
fake_rankings_t1 = {
    'rankings': [
        {'ticker': '000660', 'rank': 1}, {'ticker': '032640', 'rank': 2},
        {'ticker': '015760', 'rank': 3}, {'ticker': '282330', 'rank': 4},
        {'ticker': '023590', 'rank': 5}, {'ticker': '001060', 'rank': 6},
        {'ticker': '102710', 'rank': 7}, {'ticker': '030200', 'rank': 8},
        {'ticker': '037460', 'rank': 9}, {'ticker': '267250', 'rank': 10},
        {'ticker': '005930', 'rank': 11}, {'ticker': '119850', 'rank': 12},
        {'ticker': '000270', 'rank': 13}, {'ticker': '033100', 'rank': 14},
        {'ticker': '002380', 'rank': 15}, {'ticker': '124500', 'rank': 16},
        {'ticker': '402340', 'rank': 17}, {'ticker': '111770', 'rank': 18},
        {'ticker': '078930', 'rank': 19}, {'ticker': '086280', 'rank': 20},
        {'ticker': '017800', 'rank': 21}, {'ticker': '033500', 'rank': 22},
        {'ticker': '383220', 'rank': 23}, {'ticker': '001120', 'rank': 24},
        {'ticker': '069960', 'rank': 25}, {'ticker': '095610', 'rank': 26},
        {'ticker': '161390', 'rank': 27}, {'ticker': '190510', 'rank': 28},
        {'ticker': '004170', 'rank': 29}, {'ticker': '017670', 'rank': 30},
    ]
}
fake_rankings_t2 = {
    'rankings': [
        {'ticker': '000660', 'rank': 1}, {'ticker': '032640', 'rank': 2},
        {'ticker': '015760', 'rank': 4}, {'ticker': '282330', 'rank': 5},
        {'ticker': '023590', 'rank': 7}, {'ticker': '102710', 'rank': 8},
        {'ticker': '030200', 'rank': 9}, {'ticker': '037460', 'rank': 10},
        {'ticker': '000270', 'rank': 11}, {'ticker': '001060', 'rank': 12},
        {'ticker': '005930', 'rank': 13}, {'ticker': '002380', 'rank': 14},
        {'ticker': '267250', 'rank': 15}, {'ticker': '111770', 'rank': 18},
        {'ticker': '119850', 'rank': 20}, {'ticker': '078930', 'rank': 21},
        {'ticker': '086280', 'rank': 22}, {'ticker': '069960', 'rank': 23},
        {'ticker': '001120', 'rank': 25}, {'ticker': '161390', 'rank': 26},
        {'ticker': '033500', 'rank': 27}, {'ticker': '017800', 'rank': 28},
        {'ticker': '383220', 'rank': 29}, {'ticker': '095610', 'rank': 30},
    ]
}

# ============================================================
# 메시지 생성 — Guide → [1/3] 시장+Top30 → [2/3] AI → [3/3] 최종
# ============================================================
msg_guide = format_overview(has_ai=True)

# [1/2] 시장 + Top 30 (포트폴리오 체크)
header_lines = [
    '━━━━━━━━━━━━━━━━━━━',
    ' [1/3] 📊 시장 + Top 30',
    '━━━━━━━━━━━━━━━━━━━',
    '📅 2026년 02월 10일 기준',
    '─────────────────',
    '🟡 코스피  5,302 (+0.07%)',
    '🔴 코스닥  1,115 (-1.10%)',
    '',
    '⚡ 코스닥: 5일선↓',
    '신규 매수 시 유의하세요.',
    '─────────────────',
    '🌡️ <b>시장 위험 지표</b> — ☀️ 여름(성장국면)',
    '',
    '🏦 <b>신용시장</b>',
    '▸ HY Spread(부도위험) 2.84%',
    '  평균(3.76%)보다 낮아서 안정적이에요.',
    '▸ 한국 BBB-(회사채) 6.4%p',
    '  정상 범위에요.',
    '',
    '⚡ <b>변동성</b>',
    '▸ VIX 17.6',
    '  평균(17.4) 이상, 안정적이에요.',
    '',
    '🟢🟢🟢 3/3 안정 — 확실한 신호',
    '💰 투자 80% + 현금 20%',
    '→ 모든 지표가 안정적이에요. 평소대로 투자하세요.',
    '─────────────────',
    '💡 <b>읽는 법</b>',
    '✅매수 ⏳내일검증 🆕관찰',
    '─────────────────',
    '📊 주도 업종',
    '자동차 5 · AI반도체/메모리 3 · 통신 2',
]
header = '\n'.join(header_lines)
top30_section = format_top30(fake_pipeline, fake_exited, has_next=True, rankings_t0=fake_rankings_t0, rankings_t1=fake_rankings_t1, rankings_t2=fake_rankings_t2)
msg_main = header + '\n' + top30_section

# [2/3] AI 리스크 필터
fake_ai = """━━━━━━━━━━━━━━━━━━━
    🛡️ AI 리스크 필터
━━━━━━━━━━━━━━━━━━━

후보 종목 중 주의할 점을 AI가 점검했어요.

📰 <b>시장 동향</b>
코스피는 미국 관세 우려에도 반도체 수출 호조로 보합 마감했어요. 코스닥은 바이오·게임주 약세로 1% 넘게 하락했어요.

⚠️ <b>매수 주의</b>

<b>한국전력(015760)</b>
전기요금 인상 지연 이슈가 있어요. 정책 리스크가 있으니 분할 매수를 추천해요.
──────────────────
<b>기아(000270)</b>
미국 관세 불확실성이 남아있어요. 52주 대비 -32%로 많이 빠졌지만 추가 하락 가능성도 있으니 주의하세요."""

msg_ai = fake_ai + '\n\n👉 다음: 최종 추천 [3/3]'

# 급락 제외 테스트 데이터
fake_skipped = [
    ({'name': '이엔에프테크놀로지', 'weighted_rank': 6.2, 'ticker': '102710'}, -6.2),
]

# [3/3] 최종 추천 — AI 생성 멘트 (3일 순위 포함)
fake_ai_picks = """<b>1. SK하이닉스(000660) · 순위 1→1→1 · 비중 20%</b>
🔥 3일 연속 부동의 1위! AI 반도체 대장주로 HBM 수요와 업황 회복이 기대돼요.
──────────────────
<b>2. LG유플러스(032640) · 순위 2→2→2 · 비중 20%</b>
☀️ 안정적인 통신주로 저평가 매력과 꾸준한 배당이 돋보여요.
──────────────────
<b>3. 한국전력(015760) · 순위 3→3→4 · 비중 20%</b>
🔥 매우 낮은 PER로 밸류 매력이 뛰어나며 전기요금 정상화 기대감이 있어요.
──────────────────
<b>4. BGF리테일(282330) · 순위 4→4→5 · 비중 20%</b>
☀️ 견고한 수익성과 안정적인 편의점 사업 기반으로 꾸준한 성장이 기대돼요.
──────────────────
<b>5. 다우기술(023590) · 순위 6→5→7 · 비중 20%</b>
🔥 매력적인 밸류와 우수한 수익성, 그리고 좋은 모멘텀을 겸비했어요."""

msg_final = format_buy_recommendations(fake_picks, '2026년 02월 10일', universe_count=598, ai_picks_text=fake_ai_picks, skipped=fake_skipped)

messages = [msg_guide, msg_main, msg_ai, msg_final]

# ============================================================
# 전송
# ============================================================
PRIVATE_CHAT_ID = getattr(__import__('config'), 'TELEGRAM_PRIVATE_ID', None)
target = PRIVATE_CHAT_ID or TELEGRAM_CHAT_ID
url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'

print("=== UI Preview v8.1 ===")
print(f"Flow: Guide → [1/3] 시장+Top30 → [2/3] AI 리스크 필터 → [3/3] 최종 추천")
for i, msg in enumerate(messages):
    label = ['guide', 'market+top30 [1/3]', 'ai filter [2/3]', 'final picks [3/3]'][i]
    print(f"\n[{label}] {len(msg)} chars")

    r = requests.post(url, data={'chat_id': target, 'text': msg, 'parse_mode': 'HTML'})
    print(f"  -> {r.status_code}")
    if r.status_code != 200:
        print(f"  ERROR: {r.text[:200]}")

print("\nDone!")
