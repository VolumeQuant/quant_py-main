"""
Gemini AI 포트폴리오 브리핑 모듈

"검색은 코드가, 분석은 AI가" 원칙:
- 개별 종목 뉴스 검색 → 제거 (Grounding은 요청당 5-8개만 검색, 나머지 할루시네이션)
- 시장 동향 → AI Google Search 유지 (1개 광범위 쿼리는 안정적)
- 데이터 분석 → 코드가 포트폴리오 데이터 구성 → AI가 해석
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


def build_prompt(stock_list):
    """
    AI 브리핑 프롬프트 구성

    핵심: 개별 종목 검색 요청 없음.
    코드가 데이터를 구성하고, AI는 시장 동향(1개 검색) + 데이터 해석만 수행.
    """
    # 종목별 데이터 텍스트 구성 (코드가 수집한 팩트)
    stock_lines = []
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

        data_parts = []
        if per and per == per:  # NaN check
            data_parts.append(f"PER {per:.1f}")
        if pbr and pbr == pbr:
            data_parts.append(f"PBR {pbr:.1f}")
        if roe and roe == roe:
            data_parts.append(f"ROE {roe:.1f}%")
        data_parts.append(f"RSI {rsi:.0f}")
        data_parts.append(f"52주고점대비 {w52:+.0f}%")
        data_parts.append(f"전일비 {chg:+.1f}%")

        data_str = ', '.join(data_parts)
        stock_lines.append(f"{rank}위 {name}({ticker}) [{sector}] {data_str}")

    stock_text = '\n'.join(stock_lines)

    # 주의 종목 자동 감지 (코드가 팩트 기반으로)
    alerts = []
    for s in stock_list:
        name = s.get('name', '')
        rsi = s.get('rsi', 50)
        w52 = s.get('w52_pct', 0)
        chg = s.get('daily_chg', 0)

        flags = []
        if rsi >= 80:
            flags.append(f"RSI {rsi:.0f} 과매수")
        if rsi <= 25:
            flags.append(f"RSI {rsi:.0f} 과매도")
        if w52 <= -40:
            flags.append(f"52주고점 대비 {w52:.0f}% 급락")
        if chg <= -7:
            flags.append(f"전일 {chg:.1f}% 급락")
        if chg >= 10:
            flags.append(f"전일 {chg:.1f}% 급등")
        if flags:
            alerts.append(f"  {name}: {', '.join(flags)}")

    alert_text = '\n'.join(alerts) if alerts else '  없음'

    prompt = f"""너는 한국 주식 퀀트 포트폴리오의 AI 브리핑 담당이야.
아래 데이터는 코드가 수집한 정확한 팩트야.
네 역할은 (1) 이번 주 한국 시장 동향을 검색하고, (2) 포트폴리오 데이터를 해석해서
투자자에게 간결한 브리핑을 제공하는 거야.

[매수 후보 {len(stock_list)}종목 데이터]
{stock_text}

[코드가 감지한 주의 신호]
{alert_text}

━━━━━━━━━━━━━━━━━━━
[작업]
━━━━━━━━━━━━━━━━━━━

1. 📰 이번 주 시장: Google 검색으로 이번 주 한국 주식시장 주요 이벤트를
   2~3줄로 요약해줘. 매수 후보에 영향 줄 수 있는 것 위주로.

2. ⚠️ 주의 종목: 위 "코드가 감지한 주의 신호" 데이터를 해석해줘.
   RSI 과매수/과매도, 52주 고점 대비 급락, 전일 급등락 등
   투자자가 주의해야 할 포인트를 설명해줘.
   주의 신호가 없으면 이 섹션은 생략해.

3. 📊 포트폴리오 특징: 데이터에서 보이는 패턴을 2~3줄로 요약해줘.
   예: 섹터 편중, 밸류에이션 특징, 모멘텀 상태 등.

[규칙]
- 한국어, 친절한 말투(~예요/~해요)
- 위 데이터에 있는 팩트만 언급할 것 (데이터에 없는 뉴스/실적 추측 금지)
- 시장 동향만 Google 검색, 개별 종목은 검색하지 말 것
- 재무 수치를 그대로 나열하지 말고 해석해줘
- 총 1500자 이내"""

    return prompt


def convert_markdown_to_text(text):
    """Gemini 응답의 마크다운을 텔레그램용 텍스트로 변환"""
    result = text
    result = re.sub(r'\*\*(.+?)\*\*', r'\1', result)
    result = re.sub(r'(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)', r'\1', result)
    result = re.sub(r'#{1,3}\s*', '', result)
    result = result.replace('---', '━━━')
    return result


def run_ai_analysis(portfolio_message, stock_list):
    """
    Gemini 2.5 Flash AI 브리핑 실행

    "검색은 코드가, 분석은 AI가" 원칙:
    - 개별 종목 검색 없음 (Grounding 5-8개 한계)
    - 시장 동향만 Google Search (1개 광범위 쿼리)
    - 포트폴리오 데이터는 코드가 구성해서 전달

    Returns:
        str: 포맷된 AI 브리핑 메시지 (실패 시 None)
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
        prompt = build_prompt(stock_list)
        grounding_tool = types.Tool(google_search=types.GoogleSearch())

        print("[Gemini] AI 브리핑 요청 중...")
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[grounding_tool],
                temperature=0.3,
            ),
        )

        # 빈 응답 방어 — 1회 재시도
        analysis_text = response.text
        if not analysis_text:
            try:
                if hasattr(response, 'candidates') and response.candidates:
                    print(f"[Gemini] finish_reason: {response.candidates[0].finish_reason}")
            except Exception:
                pass
            print("[Gemini] 응답이 비어있음 — 재시도")
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[grounding_tool],
                    temperature=0.3,
                ),
            )
            analysis_text = response.text
            if not analysis_text:
                print("[Gemini] 재시도도 실패")
                return None

        print(f"[Gemini] 응답 수신: {len(analysis_text)}자")

        # 마크다운 → 텍스트 변환
        analysis_clean = convert_markdown_to_text(analysis_text)

        # 최종 메시지 구성
        now = datetime.now(KST)
        lines = [
            '━━━━━━━━━━━━━━━━━━━',
            '       🤖 AI 브리핑',
            '━━━━━━━━━━━━━━━━━━━',
            f'📅 {now.strftime("%Y년 %m월 %d일")}',
            '',
            '포트폴리오 데이터를 AI가 분석한',
            '브리핑이에요. 참고용이에요!',
            '',
            analysis_clean,
        ]

        print("[Gemini] AI 브리핑 완료")
        return '\n'.join(lines)

    except Exception as e:
        print(f"[Gemini] AI 분석 실패: {e}")
        return None


if __name__ == '__main__':
    test_stocks = [
        {'ticker': '123330', 'name': '제닉', 'rank': 1, 'sector': 'K-뷰티/화장품',
         'per': 22.5, 'pbr': 8.2, 'roe': 52.4, 'rsi': 72, 'w52_pct': -47, 'daily_chg': 7.1},
        {'ticker': '019180', 'name': '티에이치엔', 'rank': 2, 'sector': '자동차부품',
         'per': 4.4, 'pbr': 0.9, 'roe': 33.7, 'rsi': 45, 'w52_pct': -20, 'daily_chg': -0.4},
        {'ticker': '402340', 'name': 'SK스퀘어', 'rank': 3, 'sector': '투자지주/AI반도체',
         'per': 18.5, 'pbr': 3.6, 'roe': 30.5, 'rsi': 61, 'w52_pct': -12, 'daily_chg': -3.8},
    ]
    result = run_ai_analysis("테스트 메시지", test_stocks)
    if result:
        print("\n=== AI 브리핑 결과 ===")
        print(result)
    else:
        print("AI 분석 실패 또는 스킵")
