"""
Gemini AI 포트폴리오 브리핑 모듈 — v3 정량 리스크 스캐너

"검색은 코드가, 분석은 AI가" 원칙:
- 코드가 6가지 위험 플래그를 팩트로 계산 → AI는 그 팩트만 해석
- 시장 동향만 Google Search (1개 광범위 쿼리)
- 종목 구분선은 코드가 직접 삽입 (AI 의존 X)
"""

import re
import os
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')


def get_gemini_api_key():
    """Gemini API 키 로드 (환경변수 → config.py 순)"""
    key = os.environ.get('GEMINI_API_KEY', '')
    if key:
        return key

    try:
        from config import GEMINI_API_KEY
        return GEMINI_API_KEY
    except (ImportError, AttributeError):
        return ''


def compute_risk_flags(s):
    """
    종목별 위험 신호 계산 — 모델이 못 잡는 당일 이벤트만

    원칙: 4겹 검증(유니버스→멀티팩터→MA120→3일교집합)을 통과한 종목이므로
    모델이 이미 평가한 밸류에이션/가격 수준은 다시 벌점 주지 않는다.
    리스크 필터는 "당일 갑자기 발생한 이벤트"만 잡는다.

    제거된 플래그 (모델과 충돌):
    - 52주 급락: "싸게 사자" 철학과 정면 충돌 + MA120이 가치함정 차단
    - PER > 40: Value 50% 가중치 + 유니버스 PER≤60 필터와 중복
    - 전일 급락: MA120+3일교집합 통과 종목의 급락은 매수 기회
    """
    rsi = s.get('rsi', 50)
    chg = s.get('daily_chg', 0)
    vol = s.get('vol_ratio', 1)

    flags = []

    # 1. 과매수 (RSI >= 80) — 극단적 과열만 경고
    if rsi >= 80:
        flags.append(f"🔺 RSI {rsi:.0f}로 과매수 구간")

    # 2. 전일 급등 (daily_chg >= +8%) — 추격매수 위험
    if chg >= 8:
        flags.append(f"🔺 전일 +{chg:.1f}% 급등 (추격매수 주의)")

    # 3. 거래량 폭발 (vol_ratio >= 3.0) — 비정상 움직임
    if vol >= 3.0:
        flags.append(f"📊 거래량 평소 {vol:.1f}배 폭증")

    return flags


def build_prompt(stock_list, base_date=None, market_context=None):
    """
    AI 브리핑 프롬프트 구성 — v3 위험 신호 스캐너

    해외 프로젝트 구조 적용:
    1. 종목별 데이터 + 인라인 위험 신호 (코드가 계산)
    2. 위험 신호 설명 섹션
    3. 구조화된 출력 형식 (구분선은 코드가 후처리)
    4. 시장 환경 컨텍스트 (market_context)
    """
    stock_count = len(stock_list)

    # 종목별 데이터 & 위험 신호 구성
    signal_lines = []
    for s in stock_list:
        rank = int(s.get('rank', 0))
        name = s.get('name', '')
        ticker = s.get('ticker', '')
        sector = s.get('sector', '기타')

        per = s.get('per')
        pbr = s.get('pbr')
        roe = s.get('roe')
        rsi = s.get('rsi', 50)
        w52 = s.get('w52_pct', 0)
        chg = s.get('daily_chg', 0)
        vol = s.get('vol_ratio', 1)

        # Line 1: 종목 헤더
        header = f"{name} ({ticker}) · {sector} · {rank}위"

        # Line 2: 데이터 요약
        data_parts = []
        if per and per == per:
            data_parts.append(f"PER {per:.1f}")
        if pbr and pbr == pbr:
            data_parts.append(f"PBR {pbr:.1f}")
        if roe and roe == roe:
            data_parts.append(f"ROE {roe:.1f}%")
        data_parts.append(f"RSI {rsi:.0f}")
        data_parts.append(f"52주 {w52:+.0f}%")
        data_parts.append(f"전일 {chg:+.1f}%")
        if vol >= 1.5:
            data_parts.append(f"거래량 {vol:.1f}배")

        header += f"\n  {', '.join(data_parts)}"

        # Line 3: 위험 신호 (또는 "위험 신호 없음")
        flags = compute_risk_flags(s)
        if flags:
            header += "\n  " + " | ".join(flags)
        else:
            header += "\n  (위험 신호 없음)"

        signal_lines.append(header)

    signals_data = '\n\n'.join(signal_lines)

    if base_date:
        date_str = f"{base_date[:4]}-{base_date[4:6]}-{base_date[6:]}"
    else:
        date_str = datetime.now(KST).strftime('%Y-%m-%d')

    # 시장 환경 컨텍스트 블록
    market_block = ""
    if market_context:
        season = market_context.get('season', '')
        concordance = market_context.get('concordance_text', '')
        action = market_context.get('action', '')
        market_block = f"""
[현재 시장 환경 — 시스템이 판단한 베타 위험]
시장 국면: {season}
지표 일치도: {concordance}
행동 권장: {action}

→ 이 시장 환경을 종목 분석에 반영해줘.
  행동 권장에 '매도'나 '멈추'가 포함되면 더 엄격하게 봐줘.
  행동 권장에 '적극'이나 '평소대로'가 포함되면 긍정적으로 평가해줘.
"""

    prompt = f"""분석 기준일: {date_str}

아래는 한국주식 퀀트 시스템의 매수 후보 {stock_count}종목과 각 종목의 정량적 위험 신호야.
이 종목들은 밸류+퀄리티+모멘텀 멀티팩터로 선정된 거야.
네 역할: 위험 신호를 해석해서 "매수 시 주의할 종목"을 투자자에게 알려주는 거야.
{market_block}
[종목별 데이터 & 위험 신호 — 시스템이 계산한 팩트]
{signals_data}

[위험 신호 설명]
🔺 RSI 과매수 = RSI 80 이상, 극단적 과열 구간 (조정 가능성)
⚠️ 전일 급락 = 하루 -5% 이상 하락 (악재 확인 필요)
🔺 전일 급등 = 하루 +8% 이상 상승 (추격매수 위험)
📊 거래량 폭발 = 평소 3배 이상 거래 (비정상 움직임)

[출력 형식]
- 한국어, 친절하고 따뜻한 말투 (~예요/~해요 체)
- 예시: "주가가 많이 빠졌어요", "조심하시는 게 좋겠어요", "아직은 괜찮아 보여요"
- 딱딱한 보고서 말투 금지. 친구에게 설명하듯 자연스럽게.
- 인사말, 서두, 맺음말 금지. 아래 섹션부터 바로 시작.
- 총 1500자 이내.

📰 시장 동향
{date_str} 한국 주식시장 마감 결과를 Google 검색해서 2~3줄 요약해줘.
- {date_str} 시장의 핵심 이슈(원인, 테마)만. 지수 수치(코스피 몇 포인트 등)는 반복하지 마.
- "이번 주" 전체 요약은 하지 마. {date_str} 마감에 집중.
- 매수 후보에 영향 줄 수 있는 것 위주로.

⚠️ 매수 주의 종목
위 위험 신호를 종합해서 매수를 재고할 만한 종목을 골라줘.
형식: 종목명(티커)를 굵게(**) 쓰고, 1~2줄로 왜 주의해야 하는지 설명.
위험 신호가 없는 종목은 절대 여기에 넣지 마.
시스템 데이터에 없는 내용을 추측하거나 지어내지 마.
"✅ 위험 신호 없음" 섹션은 시스템이 자동 생성하니까 네가 만들지 마.
종목 사이에 구분선이나 [SEP] 같은 마커 넣지 마. 코드가 알아서 처리해."""

    return prompt


def convert_markdown_to_html(text):
    """Gemini 응답의 마크다운을 텔레그램 HTML로 변환

    순서 중요:
    1. [SEP] 잔여물 제거
    2. HTML 특수문자 이스케이프 (&, <, >)
    3. **bold** → <b>bold</b>, *italic* → <i>italic</i>
    4. ### headers → 제거, --- → ━━━
    5. ⚠️ 섹션에서 종목 사이 구분선 자동 삽입 (regex 기반)
    """
    result = text
    # Step 1: 혹시 남은 [SEP] 제거
    result = result.replace('[SEP]', '')
    # Step 2: HTML 이스케이프 (반드시 먼저)
    result = result.replace('&', '&amp;')
    result = result.replace('<', '&lt;')
    result = result.replace('>', '&gt;')
    # Step 3: 마크다운 → HTML 태그
    result = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', result)
    result = re.sub(r'(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)', r'<i>\1</i>', result)
    # Step 4: 헤더/구분선
    result = re.sub(r'#{1,3}\s*', '', result)
    result = result.replace('---', '━━━')
    # Step 5: ⚠️ 섹션에서 <b>종목명 (6자리티커)</b> 사이에 구분선 삽입
    idx = result.find('⚠️')
    if idx != -1:
        before = result[:idx]
        after = result[idx:]
        count = [0]

        def _sep(m):
            count[0] += 1
            if count[0] <= 1:
                return m.group(0)
            return f'─────────\n{m.group(0)}'

        after = re.sub(r'<b>[^<]+?\(\d{6}\)</b>', _sep, after)
        result = before + after
    # Step 6: 구분선 앞뒤 빈 줄 정리
    result = re.sub(r'\n+─────────\n+', '\n─────────\n', result)
    # 연속 빈 줄 모두 제거
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result


def extract_text(resp):
    """response.text가 None일 때 parts에서 직접 추출"""
    try:
        if resp.text:
            return resp.text
    except Exception:
        pass
    try:
        parts = resp.candidates[0].content.parts
        texts = [p.text for p in parts if hasattr(p, 'text') and p.text]
        if texts:
            return '\n'.join(texts)
    except Exception:
        pass
    return None


def run_ai_analysis(portfolio_message, stock_list, base_date=None, market_context=None):
    """
    Gemini 2.5 Flash AI 브리핑 실행 — v3 정량 리스크 스캐너

    "검색은 코드가, 분석은 AI가" 원칙:
    - 코드가 6가지 위험 플래그를 팩트로 계산
    - AI는 시장 동향 검색(1회) + 위험 신호 해석만 수행
    - Markdown → Telegram HTML 변환
    - market_context: 시장 환경 (계절, 현금비중, concordance)

    Returns:
        str: HTML 포맷된 AI 브리핑 메시지 (실패 시 None)
    """
    api_key = get_gemini_api_key()
    if not api_key:
        print("[Gemini] GEMINI_API_KEY 미설정 — AI 분석 스킵")
        return None

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print("[Gemini] google-genai 패키지 미설치 — AI 분석 스킵")
        return None

    try:
        client = genai.Client(api_key=api_key)
        prompt = build_prompt(stock_list, base_date=base_date, market_context=market_context)
        grounding_tool = types.Tool(google_search=types.GoogleSearch())

        print("[Gemini] AI 브리핑 요청 중...")
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[grounding_tool],
                temperature=0.2,
            ),
        )

        # 빈 응답 방어 — extract_text + 1회 재시도
        analysis_text = extract_text(response)
        if not analysis_text:
            try:
                if hasattr(response, 'candidates') and response.candidates:
                    print(f"[Gemini] finish_reason: {response.candidates[0].finish_reason}")
            except Exception:
                pass
            print("[Gemini] 응답이 비어있음 — 재시도 (temp 0.3)")
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[grounding_tool],
                    temperature=0.3,
                ),
            )
            analysis_text = extract_text(response)
            if not analysis_text:
                print("[Gemini] 재시도도 실패")
                return None

        print(f"[Gemini] 응답 수신: {len(analysis_text)}자")

        # 마크다운 → HTML 변환 (⚠️ 섹션 구분선 자동 삽입)
        analysis_html = convert_markdown_to_html(analysis_text)

        # ✅ 위험 신호 없음 — 코드가 직접 생성 (Gemini에 맡기면 포맷 불안정)
        clean_names = [s.get('name', '') for s in stock_list if not compute_risk_flags(s)]
        clean_section = ''
        if clean_names:
            clean_section = f'\n\n✅ 위험 신호 없음 ({len(clean_names)}종목)\n' + ', '.join(clean_names)

        # 최종 메시지 구성
        now = datetime.now(KST)
        lines = [
            '━━━━━━━━━━━━━━━━━━━',
            '    🤖 AI 리스크 필터',
            '━━━━━━━━━━━━━━━━━━━',
            '',
            '후보 종목 중 주의할 점을 AI가 점검했어요.',
            '',
            analysis_html + clean_section,
        ]

        print("[Gemini] AI 리스크 필터 완료")
        return '\n'.join(lines)

    except Exception as e:
        print(f"[Gemini] AI 분석 실패: {e}")
        return None


def build_final_picks_prompt(stock_list, weight_per_stock=20, base_date=None, market_context=None):
    """최종 추천 종목별 설명 프롬프트 (미국 프로젝트 방식)"""
    stock_lines = []
    for i, s in enumerate(stock_list):
        line = f"{i+1}. {s['name']}({s['ticker']}) · {s.get('sector', '기타')}"
        parts = []
        if s.get('rank_t0') is not None:
            rank_str = f"순위 {s.get('rank_t2', '?')}→{s.get('rank_t1', '?')}→{s['rank_t0']}"
            if s.get('driver'):
                rank_str += f"({s['driver']})"
            parts.append(rank_str)
        if s.get('per'): parts.append(f"PER {s['per']:.1f}")
        if s.get('fwd_per'): parts.append(f"Fwd PER {s['fwd_per']:.1f}")
        if s.get('roe'): parts.append(f"ROE {s['roe']:.1f}%")
        parts.append(f"RSI {s.get('rsi', 50):.0f}")
        parts.append(f"52주 {s.get('w52_pct', 0):+.0f}%")
        line += f"\n   비중 {weight_per_stock}% · {', '.join(parts)}"
        stock_lines.append(line)

    stocks_data = '\n\n'.join(stock_lines)

    if base_date:
        date_str = f"{base_date[:4]}-{base_date[4:6]}-{base_date[6:]}"
    else:
        date_str = datetime.now(KST).strftime('%Y-%m-%d')

    # 시장 환경 블록
    market_block = ""
    if market_context:
        season = market_context.get('season', '')
        action = market_context.get('action', '')
        market_block = f"""
[시장 위험 상태]
국면: {season}
행동 권장: {action}
→ 종목 설명에 시장 환경을 자연스럽게 반영해줘. 위험 높으면 "방어적", 안정적이면 "공격적" 톤으로.
"""

    return f"""아래 {len(stock_list)}종목 각각의 최근 실적/사업 성장 배경을 Google 검색해서 한 줄씩 써줘.

[종목]
{stocks_data}

[형식]
- 한국어, ~예요 체
- 종목별: **N. 종목명(티커) · 비중 {weight_per_stock}%**
  날씨아이콘 + 비즈니스 매력 한 줄
- 종목 사이에 [SEP]
- 맨 끝 별도 문구 없음

[규칙]
- 각 종목의 실적/사업 성장 배경(왜 주가가 오르는지, 어떤 사업이 잘 되는지)을 검색해서 써.
  예: "AI 반도체 수요 확대로 HBM 매출 급증 중이에요"
  예: "전력 수요 폭증에 원전 재가동 기대감까지 더해졌어요"
- 단순히 "PER 낮음", "ROE 높음"처럼 숫자만 반복하지 마. 그 숫자 뒤의 사업적 이유를 써.
- 주의/경고/유의 표현 금지. 긍정적 매력만.
- "선정", "포함", "선택" 같은 시스템 용어 금지.
- 서두/인사말/도입문 금지. 첫 번째 종목부터 바로 시작.
- 종목마다 다른 문장 구조로 써."""


def _convert_picks_markdown(text):
    """최종 추천 마크다운 → HTML 변환"""
    # Gemini 서두 제거: 첫 번째 종목(**1.) 전 텍스트 삭제
    first_stock = re.search(r'\*\*1\.', text)
    if first_stock and first_stock.start() > 0:
        text = text[first_stock.start():]
    result = text
    result = result.replace('&', '&amp;')
    result = result.replace('<', '&lt;')
    result = result.replace('>', '&gt;')
    result = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', result)
    result = re.sub(r'(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)', r'<i>\1</i>', result)
    result = re.sub(r'\n*\[SEP\]\n*', '\n──────────────────\n', result)
    result = re.sub(r'#{1,3}\s*', '', result)
    result = re.sub(r'\n{3,}', '\n\n', result)
    result = re.sub(r'\n+──────────────────\n+', '\n──────────────────\n', result)
    return result.strip()


def run_final_picks_analysis(stock_list, weight_per_stock=20, base_date=None, market_context=None):
    """최종 추천 종목별 AI 설명 생성 (미국 프로젝트 방식)"""
    api_key = get_gemini_api_key()
    if not api_key:
        print("[Gemini] GEMINI_API_KEY 미설정 — 최종 추천 AI 설명 스킵")
        return None

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print("[Gemini] google-genai 패키지 미설치 — 최종 추천 AI 설명 스킵")
        return None

    try:
        client = genai.Client(api_key=api_key)
        prompt = build_final_picks_prompt(stock_list, weight_per_stock, base_date, market_context)

        print("[Gemini] 최종 추천 설명 요청 중 (Google Search Grounding)...")
        grounding_tool = types.Tool(google_search=types.GoogleSearch())
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[grounding_tool],
                temperature=0.3,
            ),
        )

        text = extract_text(response)
        if not text:
            print("[Gemini] 최종 추천 응답 비어있음")
            return None

        html = _convert_picks_markdown(text)
        print(f"[Gemini] 최종 추천 설명 완료: {len(html)}자")
        return html

    except Exception as e:
        print(f"[Gemini] 최종 추천 설명 실패: {e}")
        return None


if __name__ == '__main__':
    test_stocks = [
        {'ticker': '402340', 'name': 'SK스퀘어', 'rank': 1, 'sector': '투자지주/AI반도체',
         'per': 18.5, 'pbr': 3.6, 'roe': 30.5, 'rsi': 61, 'w52_pct': -12, 'daily_chg': -3.8, 'vol_ratio': 1.2},
        {'ticker': '015760', 'name': '한국전력', 'rank': 29, 'sector': '전력/유틸리티',
         'per': 35.2, 'pbr': 0.4, 'roe': 1.2, 'rsi': 78, 'w52_pct': -5, 'daily_chg': 9.2, 'vol_ratio': 4.5},
        {'ticker': '000270', 'name': '기아', 'rank': 3, 'sector': '자동차',
         'per': 6.1, 'pbr': 0.8, 'roe': 18.2, 'rsi': 45, 'w52_pct': -20, 'daily_chg': -0.4, 'vol_ratio': 0.9},
    ]

    # 위험 플래그 테스트
    print("=== 위험 플래그 테스트 ===")
    for s in test_stocks:
        flags = compute_risk_flags(s)
        print(f"{s['name']}: {flags if flags else '(없음)'}")

    print("\n=== 프롬프트 미리보기 ===")
    prompt = build_prompt(test_stocks)
    print(prompt[:1000] + '...')

    print("\n=== Gemini 호출 ===")
    result = run_ai_analysis(None, test_stocks)
    if result:
        print("\n=== AI 브리핑 결과 ===")
        print(result)
    else:
        print("AI 분석 실패 또는 스킵")
