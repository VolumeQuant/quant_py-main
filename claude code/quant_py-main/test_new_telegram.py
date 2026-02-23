"""
새 텔레그램 포맷 테스트 v8 — Answer First + Storytelling + AI

핵심 철학:
  신용 없는 발신자 → 과정의 투명성 + 검증 가능한 숫자로 설득
  별도의 설명문 없이도 처음 읽는 사람이 이해할 수 있는 메시지
  전문 용어(HY, RSI, VIX 등) 대신 일반인이 아는 표현 사용

  메시지 1: 결론 → 선정 과정 → 종목별 근거(+💬AI) → 시장(+📰AI) → 리스크 → 매도
  메시지 2: Top 30 전 종목의 3일 흐름 (시스템이 살아있다는 증거)

기존 send_telegram_auto.py를 수정하지 않고,
동일 데이터를 새 포맷으로 개인봇에만 전송합니다.

실행: python test_new_telegram.py
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import re
import requests
import json
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pykrx import stock

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID
from ranking_manager import (
    load_ranking, load_recent_rankings,
    get_stock_status, get_daily_changes,
    MIN_RANK_CHANGE,
)
from credit_monitor import get_credit_status, get_market_pick_level

KST = ZoneInfo('Asia/Seoul')
MAX_PICKS = 5
WEIGHT_PER_STOCK = 20


# ============================================================
# 유틸리티
# ============================================================
def get_korea_now():
    return datetime.now(KST)


def get_recent_trading_dates(n=3):
    today = get_korea_now()
    dates = []
    for i in range(1, 30):
        date = (today - timedelta(days=i)).strftime('%Y%m%d')
        try:
            df = stock.get_market_cap(date, market='KOSPI')
            if not df.empty and df.iloc[:, 0].sum() > 0:
                dates.append(date)
                if len(dates) >= n:
                    break
        except Exception:
            continue
    return dates


def calc_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1] if not rsi.iloc[-1] != rsi.iloc[-1] else 50


def get_stock_technical(ticker, base_date):
    ticker_str = str(ticker).zfill(6)
    try:
        start = (datetime.strptime(base_date, '%Y%m%d') - timedelta(days=365)).strftime('%Y%m%d')
        ohlcv = stock.get_market_ohlcv(start, base_date, ticker_str)
        if ohlcv.empty or len(ohlcv) < 20:
            return None
        price = ohlcv.iloc[-1]['종가']
        prev_price = ohlcv.iloc[-2]['종가'] if len(ohlcv) >= 2 else price
        daily_chg = (price / prev_price - 1) * 100
        rsi = calc_rsi(ohlcv['종가'])
        return {'price': price, 'daily_chg': daily_chg, 'rsi': rsi}
    except Exception as e:
        print(f"  기술지표 실패 {ticker_str}: {e}")
        return None


def _escape_html(text):
    """HTML 특수문자 이스케이프"""
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


# ============================================================
# AI 브리핑 (Gemini) — US 프로젝트 패턴 참고
# ============================================================
def run_new_ai_analysis(picks, base_date, credit=None):
    """Gemini 2회 호출 — (1) 시장 요약 (2) 종목별 내러티브

    AI 실패 시에도 빈 결과를 반환하여 메시지 정상 작동 보장.
    Returns: {'market_summary': str, 'narratives': {ticker: str}}
    """
    from gemini_analysis import get_gemini_api_key, extract_text

    result = {'market_summary': '', 'narratives': {}}
    api_key = get_gemini_api_key()
    if not api_key:
        print("[AI] GEMINI_API_KEY 미설정 — AI 없이 진행")
        return result

    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=api_key)
        grounding_tool = types.Tool(google_search=types.GoogleSearch())
    except Exception as e:
        print(f"[AI] Gemini 초기화 실패: {e}")
        return result

    date_str = f"{base_date[:4]}년 {base_date[4:6]}월 {base_date[6:]}일"

    # ── 호출 1: 시장 요약 ──
    try:
        market_ctx = ""
        if credit:
            action = credit.get('final_action', '')
            if action:
                market_ctx = f"현재 시장 판단: {action}"

        market_prompt = f"""{date_str} 한국 주식시장 마감 결과를 Google 검색해서 2~3줄로 요약해줘.

{market_ctx}

규칙:
- 핵심 이슈(원인, 테마)만 간결하게.
- 지수 수치(코스피 몇 포인트 등)는 별도 표시하니 생략.
- 주요 이벤트 있으면 한 줄 추가.
- 한국어, ~예요 체.
- 인사말/서두/맺음말 없이 바로 시작."""

        print("[AI] 시장 요약 요청 중...")
        resp = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=market_prompt,
            config=types.GenerateContentConfig(
                tools=[grounding_tool],
                temperature=0.2,
            ),
        )
        text = extract_text(resp)
        if text:
            text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
            text = re.sub(r'#{1,3}\s*', '', text)
            result['market_summary'] = text.strip()
            print(f"[AI] 시장요약 {len(result['market_summary'])}자")
        else:
            print("[AI] 시장요약 응답 없음")
    except Exception as e:
        print(f"[AI] 시장요약 실패: {e}")

    # ── 호출 2: 종목별 내러티브 ──
    if picks:
        try:
            stock_lines = []
            for i, s in enumerate(picks):
                sector = s.get('sector', '기타')
                per = s.get('per', 0) or 0
                fwd = s.get('fwd_per', 0) or 0
                roe = s.get('roe', 0) or 0
                stock_lines.append(
                    f"{i+1}. {s['name']}({s['ticker']}) · {sector}\n"
                    f"   PER {per:.1f} · 전망PER {fwd:.1f} · ROE {roe:.1f}%"
                )

            stock_prompt = f"""아래 {len(picks)}종목 각각의 최근 실적/사업 성장 배경을 Google 검색해서 한 줄씩 써줘.

[종목]
{chr(10).join(stock_lines)}

[형식]
종목별로 한 줄씩. 종목 사이에 [SEP] 표시.
형식: 6자리티커: 설명 한 줄

[규칙]
- 각 종목의 실적/사업 성장 배경(왜 실적이 좋은지, 어떤 사업이 잘 되는지)을 검색해서 써.
  예: "005930: HBM과 AI 반도체 수요 확대로 메모리 매출이 급증하고 있어요"
  예: "015760: 전력 수요 폭증에 요금 인상 효과까지 더해졌어요"
- 단순히 "PER 낮음", "ROE 높음"처럼 숫자만 반복하지 마. 그 숫자 뒤의 사업적 이유를 써.
- 주의/경고/유의 표현 금지. 긍정적 매력만.
- 한국어, ~예요 체, 종목마다 다른 문장 구조.
- 서두/인사말/맺음말 금지. 첫 종목부터 바로 시작."""

            print("[AI] 종목 내러티브 요청 중...")
            resp = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=stock_prompt,
                config=types.GenerateContentConfig(
                    tools=[grounding_tool],
                    temperature=0.3,
                ),
            )
            text = extract_text(resp)
            if text:
                text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
                text = re.sub(r'#{1,3}\s*', '', text)

                for line in text.split('\n'):
                    line = line.strip()
                    if not line or line == '[SEP]':
                        continue
                    # "6자리티커: 설명" / "N. 6자리티커: 설명" / "- 6자리티커: 설명"
                    m = re.match(r'(?:\d+\.\s*)?(?:-\s*)?(\d{6})[\s:：]+(.{10,})', line)
                    if m:
                        ticker = m.group(1)
                        narrative = m.group(2).strip()
                        narrative = re.sub(r'^[:\s：]+', '', narrative)
                        if narrative:
                            result['narratives'][ticker] = narrative

                print(f"[AI] 내러티브 {len(result['narratives'])}종목")
            else:
                print("[AI] 내러티브 응답 없음")
        except Exception as e:
            print(f"[AI] 내러티브 실패: {e}")

    return result


# ============================================================
# 종목 정보 헬퍼
# ============================================================

def _build_signal_basis(credit):
    """시장 신호 근거 한 줄 — 전문용어 없이"""
    parts = []
    hy = credit.get('hy')
    kr = credit.get('kr')
    vix = credit.get('vix')
    if hy:
        q = hy['quadrant']
        labels = {
            'Q1': '미국 신용시장 회복',
            'Q2': '미국 신용시장 안정',
            'Q3': '미국 신용시장 경계',
            'Q4': '미국 신용시장 위험',
        }
        parts.append(labels.get(q, '미국 신용시장 ?'))
    if kr:
        kr_labels = {'정상': '한국 신용 정상', '경계': '한국 신용 경계', '위기': '한국 신용 위험'}
        parts.append(kr_labels.get(kr['regime_label'], '한국 신용 ?'))
    if vix:
        parts.append(f"변동성 {vix.get('regime_label', '?')}")
    return ', '.join(parts) if parts else '데이터 수집 중'


def _get_signal_summary(credit):
    """시장 신호 아이콘 + 레이블 + 근거"""
    n_ok, n_total = 0, 0
    for indicator, ok_check in [
        (credit.get('hy'), lambda x: x['quadrant'] in ('Q1', 'Q2')),
        (credit.get('kr'), lambda x: x['regime'] == 'normal'),
        (credit.get('vix'), lambda x: x['direction'] == 'stable'),
    ]:
        if indicator:
            n_total += 1
            if ok_check(indicator):
                n_ok += 1
    if n_total == 0:
        icon, label = "🟡", "데이터 수집 중"
    elif n_ok == n_total:
        icon, label = "🟢", "안정"
    elif n_ok == 0:
        icon, label = "🔴", "위험"
    elif n_ok >= n_total - 1:
        icon, label = "🟢", "대체로 안정"
    else:
        icon, label = "🟡", "주의"
    basis = _build_signal_basis(credit)
    return f"{icon} {label} — {basis}"


def compute_factor_tags(ticker, fr_cur, fr_prev, min_change=5):
    """팩터 등수 변화 태그 (가치↑ 품질↓ 등)"""
    r0 = fr_cur.get(ticker, {})
    rp = fr_prev.get(ticker, {})
    if not r0 or not rp:
        return ''
    tags = []
    for name in ['가치', '품질', '성장', '모멘텀']:
        cur = r0.get(name)
        prev = rp.get(name)
        if cur is not None and prev is not None:
            diff = prev - cur  # 양수 = 등수 개선 (숫자 줄어듦)
            if abs(diff) >= min_change:
                arrow = '↑' if diff > 0 else '↓'
                tags.append(f"{name}{arrow}")
    return ' '.join(tags)


def _filter_neg_tags(tag_str):
    """이탈 종목용: 부정 태그만 추출 (↓만)"""
    if not tag_str:
        return ''
    parts = tag_str.split()
    neg = [p for p in parts if '↓' in p]
    return ' '.join(neg)


def compute_factor_ranks(rankings):
    """각 팩터별 등수 계산 (높은 점수 = 높은 등수)"""
    stocks = rankings.get('rankings', [])
    if not stocks:
        return {}
    factor_keys = {
        'value_s': '가치', 'quality_s': '품질',
        'growth_s': '성장', 'momentum_s': '모멘텀',
    }
    result = {}
    for key, name in factor_keys.items():
        scored = [(s['ticker'], s.get(key, 0) or 0) for s in stocks]
        scored.sort(key=lambda x: -x[1])
        for rank, (ticker, _) in enumerate(scored, 1):
            if ticker not in result:
                result[ticker] = {}
            result[ticker][name] = rank
    return result


def _get_factor_rank_str(pick, threshold=30):
    """강한 팩터만 등수 표시 (threshold 이내)"""
    ranks = pick.get('_factor_ranks', {})
    if not ranks:
        return ''
    strong = [(n, r) for n, r in ranks.items() if r <= threshold]
    strong.sort(key=lambda x: x[1])
    if not strong:
        best = min(ranks.items(), key=lambda x: x[1])
        strong = [best]
    return ' · '.join(f"{n} {r}등" for n, r in strong)


# ============================================================
# 메시지 1 — 추천 + 근거 + AI + 시장
# ============================================================
def format_msg1(
    base_date_str, kospi_close, kospi_chg, kosdaq_close, kosdaq_chg,
    credit, pick_level, market_max_picks, stock_weight,
    picks, risk_warnings, exited, rankings_t0, cold_start,
    pipeline=None, ai_content=None,
):
    lines = []
    narratives = ai_content.get('narratives', {}) if ai_content else {}
    market_summary = ai_content.get('market_summary', '') if ai_content else ''

    lines.append(f"<b>KOREA QUANT</b> · {base_date_str}")

    # 콜드 스타트
    if cold_start:
        lines.append("")
        lines.append(f"코스피 {kospi_close:,.0f}({kospi_chg:+.1f}%)")
        lines.append(f"코스닥 {kosdaq_close:,.0f}({kosdaq_chg:+.1f}%)")
        lines.append("")
        lines.append("데이터 축적 중이에요.")
        lines.append("3거래일 후 매수 후보가 선정돼요.")
        lines.append("")
        lines.append("<i>참고용이며, 투자 판단은 본인 책임이에요.</i>")
        return '\n'.join(lines)

    # ── ① 결론: 매수 후보 ──
    if market_max_picks == 0 and pick_level.get('warning'):
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━")
        lines.append(f"<b>🚫 매수 중단</b>")
        lines.append("━━━━━━━━━━━━━━━")
        lines.append(pick_level['warning'])
        lines.append("시장이 안정되면 추천이 자동 재개돼요.")
    elif picks:
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━")
        lines.append(f"<b>🛒 매수 후보 TOP {len(picks)}</b> (각 {stock_weight}%)")
        lines.append("━━━━━━━━━━━━━━━")
        for i, p in enumerate(picks):
            ticker_str = str(p['ticker']).zfill(6)
            lines.append(f"<b>{i+1}. {p['name']}({ticker_str})</b>")

    # ── ② 선정 과정 ──
    meta = rankings_t0.get('metadata') or {}
    universe_count = meta.get('total_universe', 0)
    if picks:
        prefilter_n = meta.get('prefilter_passed', 0)
        v_count = sum(1 for s in (pipeline or []) if s['status'] == '✅')
        lines.append("")
        lines.append(f"<b>📋 선정 과정</b>")
        if universe_count > 0:
            lines.append(f"시총 3천억 이상 · 거래 활발한 {universe_count:,}종목에서")
            if prefilter_n > 0:
                lines.append(f"→ 이익 대비 싸고 수익성 높은 상위 {prefilter_n}개 선별")
            lines.append("→ 11개 지표로 종합 채점")
            lines.append("  가치 — PER·PBR·PCR·PSR·배당률")
            lines.append("  품질 — ROE·매출이익률·현금흐름")
            lines.append("  성장 — 이익개선도·매출성장률")
            lines.append("  모멘텀 — 위험조정 수익률")
            lines.append(f"→ 상위 30개 → 3일 검증 → {v_count}개 통과")
            lines.append(f"→ 리스크 점검 → 최종 {len(picks)}종목")

    # ── ③ 종목별 근거 ──
    if picks:
        universe_str = f" ({universe_count:,}종목 중)" if universe_count else ""
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━")
        lines.append(f"<b>📌 종목별 근거</b>")
        lines.append("━━━━━━━━━━━━━━━")
        for i, pick in enumerate(picks):
            if i > 0:
                lines.append("─ ─ ─ ─ ─ ─ ─ ─")
            name = pick['name']
            rank = pick['rank']
            sector = pick.get('sector', '')

            # 순위 — "(N종목 중)" 포함
            r2 = pick.get('_r2')
            r1 = pick.get('_r1')
            if r2 is not None and r1 is not None:
                traj = f"3일순위 {r2}→{r1}→{rank}위{universe_str}"
            elif r1 is not None:
                traj = f"2일순위 {r1}→{rank}위{universe_str}"
            else:
                traj = f"순위 {rank}위{universe_str}"

            # 변동 사유 태그
            driver = pick.get('_driver', '')
            driver_str = f" {driver}" if driver else ""

            price = pick.get('price')
            price_str = f" · {price:,.0f}원" if price else ""
            lines.append(f"<b>{i+1}. {name}</b> {sector}{price_str}")
            lines.append(f"{traj}{driver_str}")

            # 팩터 등수 (강한 팩터만)
            factor_str = _get_factor_rank_str(pick)
            if factor_str:
                lines.append(factor_str)

            # 💬 AI 내러티브 — 왜 이 종목인지 사업 배경
            narrative = narratives.get(pick['ticker'], '')
            if narrative:
                lines.append(f"💬 {_escape_html(narrative)}")

    # ── ④ 시장 환경 ──
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━")
    lines.append(f"<b>📊 시장 환경</b>")
    lines.append("━━━━━━━━━━━━━━━")
    lines.append(f"코스피 {kospi_close:,.0f}({kospi_chg:+.1f}%)")
    lines.append(f"코스닥 {kosdaq_close:,.0f}({kosdaq_chg:+.1f}%)")
    lines.append("")
    # 시장 신호 — 카테고리별 분리
    hy = credit.get('hy')
    vix = credit.get('vix')
    if hy and hy.get('hy_spread'):
        spread = hy['hy_spread']
        median = hy.get('median_10y', 0)
        ok = spread < median
        icon = '🟢' if ok else '🔴'
        desc = f"평균({median:.2f}%)보다 낮아 안정" if ok else f"평균({median:.2f}%)보다 높아 경계"
        lines.append(f"{icon} 신용시장 — 회사채 위험도 {spread:.2f}%")
        lines.append(f"  {desc}")
    if vix and vix.get('vix_current'):
        vix_desc = {
            '안정': ('🟢', '평소 수준'),
            '보통': ('🟢', '평소보다 다소 높지만 정상 범위'),
            '안정화': ('🟢', '높았지만 안정화 중'),
            '경계': ('🟡', '평소보다 높음'),
            '높지만안정': ('🟡', '높지만 안정화 중'),
            '상승경보': ('🔴', '빠르게 상승 중'),
            '위기': ('🔴', '매우 높음'),
            '공포완화': ('🟡', '공포에서 회복 중'),
            '안일': ('🟡', '너무 낮음'),
        }
        regime = vix.get('regime_label', '')
        icon, desc = vix_desc.get(regime, ('🟡', regime))
        lines.append(f"{icon} 변동성 — VIX {vix['vix_current']:.1f}")
        lines.append(f"  {desc}")
    # 종합 판단
    signal = _get_signal_summary(credit)
    lines.append("")
    lines.append(signal)

    # 📰 AI 시장 요약 — 당일 이슈 정리
    if market_summary:
        lines.append("")
        lines.append(f"📰 {_escape_html(market_summary)}")

    # ── ⑤ 주의 ──
    if risk_warnings:
        lines.append("")
        lines.append(f"<b>⚠️ 주의</b>")
        for w in risk_warnings:
            lines.append(w)

    # ── ⑥ 매도 검토 ──
    if exited:
        lines.append("")
        lines.append(f"<b>🔔 매도 검토</b>")
        for e in exited:
            tag = e.get('_exit_tag', '')
            reason = f' {tag}' if tag else ''
            lines.append(f"{e['name']}{reason} — 상위 30위 이탈")
        lines.append("보유 중이라면 매도를 검토하세요.")
        lines.append("<i>(상세 순위 변화는 다음 메시지)</i>")

    # 푸터
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━")
    lines.append("<i>순위는 그제→어제→오늘 · 등수는 채점 대상 중</i>")
    lines.append("<i>참고용이며, 투자 판단은 본인 책임이에요.</i>")
    return '\n'.join(lines)


# ============================================================
# 메시지 2 — Top 30 전 종목 흐름 (시스템 증거)
# ============================================================
def format_msg2(pipeline, exited, rankings_t0):
    """Top 30 전 종목의 궤적 + 변동 사유."""
    lines = []
    lines.append("<b>KOREA QUANT</b>")
    lines.append("<b>Top 30 전체 흐름</b>")
    lines.append("이 목록에 있으면 보유, 빠지면 매도 검토.")
    lines.append("<i>↑ 개선 ↓ 악화 (가치·품질·성장·모멘텀)</i>")

    verified = [s for s in pipeline if s['status'] == '✅']
    two_day = [s for s in pipeline if s['status'] == '⏳']
    new_stocks = [s for s in pipeline if s['status'] == '🆕']

    # ✅ 3일 검증 완료 — 매수 대상 (태그 없음, 안정 구간)
    if verified:
        verified.sort(key=lambda x: x['rank'])
        lines.append("")
        lines.append(f"<b>✅ 3일 검증 완료 ({len(verified)}종목)</b>")
        lines.append("3거래일 연속 상위 30위 유지 → 매수 대상")
        for s in verified:
            r2 = s.get('_r2')
            r1 = s.get('_r1')
            rank = s['rank']
            if r2 is not None and r1 is not None:
                traj = f"{r2}→{r1}→{rank}위"
            else:
                traj = f"{rank}위"
            lines.append(f"{s['name']} {traj}")

    # ⏳ 2일째 관찰 — 내일 검증 완료
    if two_day:
        two_day.sort(key=lambda x: x['rank'])
        lines.append("")
        lines.append(f"<b>⏳ 2일째 관찰 ({len(two_day)}종목)</b>")
        lines.append("내일도 30위 이내 유지 시 매수 대상")
        for s in two_day:
            r1 = s.get('_r1')
            rank = s['rank']
            if r1 is not None:
                traj = f"{r1}→{rank}위"
            else:
                traj = f"{rank}위"
            driver = s.get('_driver', '')
            d_str = f" {driver}" if driver else ""
            lines.append(f"{s['name']} {traj}{d_str}")

    # 🆕 오늘 첫 진입
    if new_stocks:
        new_stocks.sort(key=lambda x: x['rank'])
        lines.append("")
        lines.append(f"<b>🆕 오늘 첫 진입 ({len(new_stocks)}종목)</b>")
        lines.append("3일 검증 시작 → 모레 매수 대상 가능")
        for s in new_stocks:
            lines.append(f"{s['name']} {s['rank']}위")

    # 📉 이탈 — 매도 검토
    if exited:
        t0_full = {item['ticker']: item for item in rankings_t0.get('rankings', [])}
        lines.append("")
        lines.append(f"<b>📉 이탈 ({len(exited)}종목)</b>")
        lines.append("상위 30위에서 밀려남 → 매도 검토")
        for e in exited:
            prev = e['rank']
            t0_item = t0_full.get(e['ticker'])
            cur = t0_item['rank'] if t0_item else None
            tag = e.get('_exit_tag', '')
            reason = f" {tag}" if tag else ""
            if cur:
                lines.append(f"{e['name']} {prev}→{cur}위{reason}")
            else:
                lines.append(f"{e['name']} {prev}위 → 밖{reason}")

    # 주도 업종
    sector_map = {}
    for item in rankings_t0.get('rankings', []):
        s = item.get('sector', '기타')
        if s == item.get('name', ''):
            s = '기타'
        if item['rank'] <= 30:
            sector_map[s] = sector_map.get(s, 0) + 1
    if sector_map:
        sorted_sectors = sorted(sector_map.items(), key=lambda x: -x[1])[:6]
        lines.append("")
        lines.append("<b>📊 주도 업종</b> (상위 30위 기준)")
        row = []
        for sec, cnt in sorted_sectors:
            row.append(f"{sec} {cnt}")
            if len(row) == 3:
                lines.append(' · '.join(row))
                row = []
        if row:
            lines.append(' · '.join(row))

    # 푸터
    lines.append("")
    lines.append("<i>참고용이며, 투자 판단은 본인 책임이에요.</i>")
    return '\n'.join(lines)


# ============================================================
# 메인
# ============================================================
def main():
    print("=" * 50)
    print("새 텔레그램 포맷 v8 테스트 (개인봇)")
    print("=" * 50)

    # 거래일 탐색
    trading_dates = get_recent_trading_dates(3)
    if not trading_dates:
        print("거래일을 찾을 수 없습니다.")
        sys.exit(1)

    BASE_DATE = trading_dates[0]
    print(f"기준일: T-0={trading_dates[0]}", end="")
    if len(trading_dates) >= 2:
        print(f", T-1={trading_dates[1]}", end="")
    if len(trading_dates) >= 3:
        print(f", T-2={trading_dates[2]}", end="")
    print()

    # 시장 지수
    idx_start = (datetime.strptime(BASE_DATE, '%Y%m%d') - timedelta(days=120)).strftime('%Y%m%d')
    kospi_idx = stock.get_index_ohlcv(idx_start, BASE_DATE, '1001')
    kosdaq_idx = stock.get_index_ohlcv(idx_start, BASE_DATE, '2001')

    kospi_close = kospi_idx.iloc[-1, 3]
    kospi_prev = kospi_idx.iloc[-2, 3] if len(kospi_idx) > 1 else kospi_close
    kospi_chg = ((kospi_close / kospi_prev) - 1) * 100

    kosdaq_close = kosdaq_idx.iloc[-1, 3]
    kosdaq_prev = kosdaq_idx.iloc[-2, 3] if len(kosdaq_idx) > 1 else kosdaq_close
    kosdaq_chg = ((kosdaq_close / kosdaq_prev) - 1) * 100

    base_date_str = f"{BASE_DATE[:4]}.{BASE_DATE[4:6]}.{BASE_DATE[6:]}"
    print(f"코스피 {kospi_close:,.0f}({kospi_chg:+.1f}%) 코스닥 {kosdaq_close:,.0f}({kosdaq_chg:+.1f}%)")

    # 시장 위험 지표
    ecos_key = getattr(__import__('config'), 'ECOS_API_KEY', None)
    credit = get_credit_status(ecos_api_key=ecos_key)
    pick_level = get_market_pick_level(credit)
    market_max_picks = pick_level['max_picks']
    stock_weight = WEIGHT_PER_STOCK if market_max_picks == 5 else (100 // market_max_picks if market_max_picks > 0 else 0)
    print(f"행동: {credit.get('final_action', '?')} · 최대 {market_max_picks}종목")

    # 순위 로드
    ranking_data = load_recent_rankings(trading_dates)
    rankings_t0 = ranking_data.get(trading_dates[0])
    rankings_t1 = ranking_data.get(trading_dates[1]) if len(trading_dates) >= 2 else None
    rankings_t2 = ranking_data.get(trading_dates[2]) if len(trading_dates) >= 3 else None

    if rankings_t0 is None:
        print(f"T-0 ({trading_dates[0]}) 순위 없음!")
        sys.exit(1)

    cold_start = rankings_t1 is None or rankings_t2 is None
    if cold_start:
        print("콜드 스타트 — 3일 교집합 불가")

    # 팩터별 등수 계산 (3일분)
    factor_ranks_t0 = compute_factor_ranks(rankings_t0)
    factor_ranks_t1 = compute_factor_ranks(rankings_t1) if rankings_t1 else {}
    factor_ranks_t2 = compute_factor_ranks(rankings_t2) if rankings_t2 else {}

    # 파이프라인
    pipeline = get_stock_status(rankings_t0, rankings_t1, rankings_t2)
    v_count = sum(1 for s in pipeline if s['status'] == '✅')
    print(f"파이프라인: ✅{v_count} ⏳{sum(1 for s in pipeline if s['status'] == '⏳')} 🆕{sum(1 for s in pipeline if s['status'] == '🆕')}")

    # ============================================================
    # 전체 파이프라인 종목에 궤적 + 변동사유 계산
    # ============================================================
    t1_full = {r['ticker']: r for r in rankings_t1.get('rankings', [])} if rankings_t1 else {}
    t2_full = {r['ticker']: r for r in rankings_t2.get('rankings', [])} if rankings_t2 else {}

    for s in pipeline:
        s['_factor_ranks'] = factor_ranks_t0.get(s['ticker'], {})
        t1_item = t1_full.get(s['ticker'])
        t2_item = t2_full.get(s['ticker'])

        if s['status'] == '✅':
            s['_r1'] = t1_item['rank'] if t1_item else s['rank']
            s['_r2'] = t2_item['rank'] if t2_item else s.get('_r1', s['rank'])
            # ✅: T-0 vs T-2 팩터 등수 변화
            if t2_item and abs(s['rank'] - s['_r2']) >= MIN_RANK_CHANGE:
                s['_driver'] = compute_factor_tags(s['ticker'], factor_ranks_t0, factor_ranks_t2)
            else:
                s['_driver'] = ''
        elif s['status'] == '⏳':
            s['_r1'] = t1_item['rank'] if t1_item else s['rank']
            s['_r2'] = None
            # ⏳: T-0 vs T-1 팩터 등수 변화
            if t1_item and abs(s['rank'] - s['_r1']) >= MIN_RANK_CHANGE:
                s['_driver'] = compute_factor_tags(s['ticker'], factor_ranks_t0, factor_ranks_t1)
            else:
                s['_driver'] = ''
        else:
            s['_r1'] = None
            s['_r2'] = None
            s['_driver'] = ''

    # 이탈 종목
    entered, exited = [], []
    if not cold_start and rankings_t1:
        entered, exited = get_daily_changes(rankings_t0, rankings_t1)
        for e in exited:
            full_tag = compute_factor_tags(e['ticker'], factor_ranks_t0, factor_ranks_t1)
            e['_exit_tag'] = _filter_neg_tags(full_tag)
        print(f"일일 변동: 진입 {len(entered)}, 이탈 {len(exited)}")

    # ============================================================
    # 매수 후보 선정 (✅ 검증 종목, rank 순)
    # ============================================================
    picks = []
    risk_warnings = []
    if not cold_start:
        verified = [s for s in pipeline if s['status'] == '✅']
        verified.sort(key=lambda x: x['rank'])

        # 기술 지표
        from gemini_analysis import compute_risk_flags

        for candidate in verified:
            tech = get_stock_technical(candidate['ticker'], BASE_DATE)
            candidate['_tech'] = tech
            if tech:
                rsi = tech.get('rsi', 50)
                chg = tech.get('daily_chg', 0)
                flags = compute_risk_flags({
                    'rsi': rsi, 'daily_chg': chg, 'vol_ratio': 1,
                })
                candidate['_flags'] = flags
                print(f"  {candidate['name']}: rank {candidate['rank']}, RSI {rsi:.0f}")

        # 리스크 없는 종목 우선
        flagged_tickers = set()
        for c in verified:
            if c.get('_flags'):
                flagged_tickers.add(c['ticker'])

        clean = [c for c in verified if c['ticker'] not in flagged_tickers]
        flagged = [c for c in verified if c['ticker'] in flagged_tickers]
        picks = (clean + flagged)[:market_max_picks]

        # 리스크 경고 — 매수 후보에 포함된 종목만
        pick_tickers = {p['ticker'] for p in picks}
        for candidate in verified:
            if candidate['ticker'] not in pick_tickers:
                continue
            tech = candidate.get('_tech')
            if tech and candidate.get('_flags'):
                rsi = tech.get('rsi', 50)
                chg = tech.get('daily_chg', 0)
                name = candidate['name']
                if rsi >= 80:
                    risk_warnings.append(f"{name} 단기 과열 — 신규 매수 자제")
                if chg <= -5:
                    risk_warnings.append(f"{name} 전일 {chg:.1f}% 급락 — 원인 확인 필요")
                if chg >= 8:
                    risk_warnings.append(f"{name} 전일 +{chg:.1f}% 급등 — 추격 매수 자제")
        print(f"최종 picks: {len(picks)}종목")

    # ============================================================
    # AI 브리핑 (Gemini)
    # ============================================================
    ai_content = None
    if picks:
        ai_content = run_new_ai_analysis(picks, BASE_DATE, credit)

    # ============================================================
    # 메시지 생성
    # ============================================================
    msg1 = format_msg1(
        base_date_str, kospi_close, kospi_chg, kosdaq_close, kosdaq_chg,
        credit, pick_level, market_max_picks, stock_weight,
        picks, risk_warnings, exited, rankings_t0, cold_start,
        pipeline=pipeline, ai_content=ai_content,
    )

    msg2 = format_msg2(pipeline, exited, rankings_t0)

    messages = [msg1, msg2]

    # ============================================================
    # 미리보기
    # ============================================================
    print("\n" + "=" * 50)
    print("새 포맷 미리보기")
    print("=" * 50)
    for i, msg in enumerate(messages):
        print(f"\n--- 메시지 {i+1} ({len(msg)}자) ---")
        print(msg)

    total_chars = sum(len(m) for m in messages)
    print(f"\n총 {len(messages)}개 메시지, {total_chars}자")

    # ============================================================
    # 개인봇으로 전송
    # ============================================================
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    results = []
    for msg in messages:
        r = requests.post(url, data={
            'chat_id': TELEGRAM_PRIVATE_ID,
            'text': msg,
            'parse_mode': 'HTML',
        })
        results.append(r.status_code)
        if r.status_code != 200:
            print(f"전송 실패: {r.text}")

    print(f"\n개인봇 전송: {', '.join(map(str, results))}")
    print("완료!")


if __name__ == '__main__':
    main()
