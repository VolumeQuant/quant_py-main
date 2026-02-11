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
    종목별 위험 신호 계산 (코드가 팩트 기반으로 판별)

    "좋은 사과를 싸게 사자" 철학:
    - 과매수/고평가/급등 = 비싼 사과 경고
    - 52주 급락/전일 급락 = 가격 하락 원인 확인 필요
    - 거래량 폭발 = 비정상 움직임 주의
    """
    rsi = s.get('rsi', 50)
    w52 = s.get('w52_pct', 0)
    chg = s.get('daily_chg', 0)
    per = s.get('per')
    vol = s.get('vol_ratio', 1)

    flags = []

    # 1. 과매수 (RSI >= 75)
    if rsi >= 75:
        flags.append(f"🔺 RSI {rsi:.0f}로 과매수 구간")

    # 2. 52주 급락 (w52_pct <= -35%)
    if w52 <= -35:
        flags.append(f"📉 52주 고점 대비 {w52:.0f}% 급락")

    # 3. 전일 급락 (daily_chg <= -5%)
    if chg <= -5:
        flags.append(f"⚠️ 전일 {chg:.1f}% 급락")

    # 4. 전일 급등 (daily_chg >= +8%)
    if chg >= 8:
        flags.append(f"🔺 전일 +{chg:.1f}% 급등 (추격매수 주의)")

    # 5. 고평가 (PER > 40)
    if per and per == per and per > 40:  # NaN check
        flags.append(f"💰 PER {per:.1f}배 고평가")

    # 6. 거래량 폭발 (vol_ratio >= 3.0)
    if vol >= 3.0:
        flags.append(f"📊 거래량 평소 {vol:.1f}배 폭증")

    return flags


def build_prompt(stock_list, base_date=None):
    """
    AI 브리핑 프롬프트 구성 — v3 위험 신호 스캐너

    해외 프로젝트 구조 적용:
    1. 종목별 데이터 + 인라인 위험 신호 (코드가 계산)
    2. 위험 신호 설명 섹션
    3. 구조화된 출력 형식 (구분선은 코드가 후처리)
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

    prompt = f"""분석 기준일: {date_str}

아래는 한국주식 퀀트 시스템의 매수 후보 {stock_count}종목과 각 종목의 정량적 위험 신호야.
이 종목들은 밸류+퀄리티+모멘텀 멀티팩터로 선정된 거야.
네 역할: 위험 신호를 해석해서 "매수 시 주의할 종목"을 투자자에게 알려주는 거야.

[종목별 데이터 & 위험 신호 — 시스템이 계산한 팩트]
{signals_data}

[위험 신호 설명]
🔺 RSI 과매수 = RSI 75 이상, 단기 과열 구간 (조정 가능성)
📉 52주 급락 = 고점 대비 35% 이상 하락 (하락 원인 확인 필요)
⚠️ 전일 급락 = 하루 -5% 이상 하락 (악재 확인 필요)
🔺 전일 급등 = 하루 +8% 이상 상승 (추격매수 위험)
💰 고평가 = PER 40배 초과 (밸류에이션 부담)
📊 거래량 폭발 = 평소 3배 이상 거래 (비정상 움직임)

[출력 형식]
- 한국어, 친절하고 따뜻한 말투 (~예요/~해요 체)
- 예시: "주가가 많이 빠졌어요", "조심하시는 게 좋겠어요", "아직은 괜찮아 보여요"
- 딱딱한 보고서 말투 금지. 친구에게 설명하듯 자연스럽게.
- 총 1500자 이내.

📰 시장 동향
이번 주 한국 주식시장 주요 이벤트를 Google 검색해서 2~3줄 요약해줘.
매수 후보에 영향 줄 수 있는 것 위주로.

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


def run_ai_analysis(portfolio_message, stock_list, base_date=None):
    """
    Gemini 2.5 Flash AI 브리핑 실행 — v3 정량 리스크 스캐너

    "검색은 코드가, 분석은 AI가" 원칙:
    - 코드가 6가지 위험 플래그를 팩트로 계산
    - AI는 시장 동향 검색(1회) + 위험 신호 해석만 수행
    - Markdown → Telegram HTML 변환

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
        prompt = build_prompt(stock_list, base_date=base_date)
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
            '    🛡️ AI 리스크 필터',
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


def build_final_picks_prompt(stock_list, weight_per_stock=20, base_date=None):
    """최종 추천 종목별 설명 프롬프트 (미국 프로젝트 방식)"""
    stock_lines = []
    for i, s in enumerate(stock_list):
        line = f"{i+1}. {s['name']}({s['ticker']}) · {s.get('sector', '기타')}"
        parts = []
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

    return f"""분석 기준일: {date_str}

아래는 한국주식 퀀트 시스템이 자동 선정한 {len(stock_list)}종목 최종 포트폴리오야.
선정 기준: 밸류+퀄리티+모멘텀 멀티팩터 상위, 3거래일 연속 Top 30 유지, AI 리스크 필터 통과.

[포트폴리오]
{stocks_data}

[출력 형식]
- 한국어, 친절하고 따뜻한 말투 (~예요/~해요 체)
- 각 종목을 아래 형식으로 출력:
  **N. 종목명(티커) · 비중 {weight_per_stock}%**
  날씨아이콘 1~2줄 선정 이유
- 날씨아이콘: 🔥 매우 좋음, ☀️ 좋음, 🌤️ 양호, ⛅ 보통
- 종목과 종목 사이에 반드시 [SEP] 한 줄을 넣어서 구분해줘.
- 맨 끝에 별도 문구 넣지 마. (코드에서 추가함)
- 500자 이내

각 종목의 비중과 선정 이유를 설명해줘.
시스템 데이터에 없는 내용을 지어내지 마."""


def _convert_picks_markdown(text):
    """최종 추천 마크다운 → HTML 변환"""
    result = text
    result = result.replace('&', '&amp;')
    result = result.replace('<', '&lt;')
    result = result.replace('>', '&gt;')
    result = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', result)
    result = re.sub(r'(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)', r'<i>\1</i>', result)
    result = result.replace('[SEP]', '──────────────────')
    result = re.sub(r'#{1,3}\s*', '', result)
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip()


def run_final_picks_analysis(stock_list, weight_per_stock=20, base_date=None):
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
        prompt = build_final_picks_prompt(stock_list, weight_per_stock, base_date)

        print("[Gemini] 최종 추천 설명 요청 중...")
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
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
