"""
Gemini AI 포트폴리오 리스크 분석 모듈

텔레그램 포트폴리오 메시지를 기반으로 Gemini 2.5 Flash에
Google Search Grounding으로 실시간 뉴스 검색 후 리스크 체크
"""

import re
import os
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')


def get_gemini_api_key():
    """Gemini API 키 로드 (환경변수 → config.py 순)"""
    # 환경변수 우선 (GitHub Actions)
    key = os.environ.get('GEMINI_API_KEY', '')
    if key:
        return key

    # config.py에서 로드
    try:
        from config import GEMINI_API_KEY
        return GEMINI_API_KEY
    except (ImportError, AttributeError):
        return ''


def strip_html(text):
    """HTML 태그 제거"""
    return re.sub(r'<[^>]+>', '', text or '')


def build_prompt(portfolio_message, stock_list):
    """
    Gemini 프롬프트 구성

    Args:
        portfolio_message: 텔레그램에 보낸 포트폴리오 메시지 텍스트
        stock_list: [{'ticker': '005930', 'name': '삼성전자', 'sector': '반도체', ...}, ...]
    """
    # 종목 리스트 텍스트
    stock_lines = []
    for s in stock_list:
        rank = int(s.get('rank', 0))
        name = s.get('name', '')
        ticker = s.get('ticker', '')
        sector = s.get('sector', '기타')
        stock_lines.append(f"{rank}위 {name}({ticker}) - {sector}")

    stock_text = '\n'.join(stock_lines)

    prompt = f"""당신은 한국 주식 포트폴리오 리스크 스캐너입니다.
소거법(elimination method)으로 매수 후보에서 제외할 종목을 찾는 것이 목적입니다.

아래는 퀀트 시스템이 선정한 매수 후보 {len(stock_list)}종목입니다:

{stock_text}

━━━━━━━━━━━━━━━━━━━
[작업 지시]
━━━━━━━━━━━━━━━━━━━

각 종목에 대해 최근 1~2주 이내 한국어 뉴스를 Google 검색하여 리스크를 체크하세요.

[리스크 카테고리] (이것만 보고)
• 소송/법적 분쟁/판결
• 규제 조사/제재
• 제품 리콜/결함/사고
• 해킹/보안 사고
• 대주주/내부자 대량 매도
• 공매도 리포트
• 실적 미스/가이던스 하향
• 신용등급 하락
• 유동성 위기/자금 경색
• 직접적 정책/관세/규제 영향
• 최대주주 변경/경영권 분쟁

[규칙]
1. 반드시 Google 검색 결과에서 찾은 구체적 뉴스만 언급할 것
2. 일반적 리스크("경쟁 심화", "변동성" 등) 절대 언급 금지
3. 긍정적 뉴스 언급 금지
4. 재무 수치(매출 XX억, EPS XX원) 나열 금지
5. 시스템 출력 데이터(PER, PBR, RSI 등) 반복 금지
6. 검색에서 리스크가 안 나오면 ✅에 넣을 것

[출력 형식] (한국어, 총 1500자 이내)

📰 이번 주 시장
(매수 후보에 영향 줄 시장 전반 이벤트 2~3줄)

🚫 주의 (리스크 발견)
종목명 → 날짜 구체적 리스크 내용
(예: 제닉 → 2/5 대주주 지분 매도 공시)

📅 실적발표 임박 (변동성 주의)
종목명 일자
(예: SK하이닉스 2/20)

✅ 리스크 미발견
나머지 종목명 나열
"""
    return prompt


def convert_markdown_to_text(text):
    """Gemini 응답의 마크다운을 텔레그램용 텍스트로 변환"""
    result = text
    # **bold** → 그대로 텍스트 (텔레그램 plain text 모드)
    result = re.sub(r'\*\*(.+?)\*\*', r'\1', result)
    # *italic* → 그대로
    result = re.sub(r'(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)', r'\1', result)
    # ### headings → 제거
    result = re.sub(r'#{1,3}\s*', '', result)
    # --- → 구분선
    result = result.replace('---', '━━━')
    return result


def format_risk_sections(text):
    """🚫 리스크 섹션에 구분선 추가"""
    lines = text.split('\n')
    new_lines = []
    in_risk_section = False
    prev_was_bullet = False

    for line in lines:
        stripped = line.strip()

        if '🚫' in stripped:
            in_risk_section = True
            prev_was_bullet = False
        elif stripped.startswith(('📅', '✅', '📰')):
            in_risk_section = False
            prev_was_bullet = False

        if in_risk_section and ('→' in stripped or stripped.startswith(('•', '-', '*'))):
            if prev_was_bullet:
                new_lines.append('──────────────────')
            prev_was_bullet = True
        else:
            if stripped:
                prev_was_bullet = False

        new_lines.append(line)

    return '\n'.join(new_lines)


def run_ai_analysis(portfolio_message, stock_list):
    """
    Gemini 2.5 Flash 리스크 스캐너 실행

    Args:
        portfolio_message: 텔레그램 포트폴리오 메시지 텍스트
        stock_list: 종목 리스트 (dict list)

    Returns:
        str: 포맷된 AI 분석 메시지 (실패 시 None)
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
        # 클라이언트 초기화
        client = genai.Client(api_key=api_key)

        # 프롬프트 구성
        prompt = build_prompt(portfolio_message, stock_list)

        # Google Search Grounding으로 실시간 뉴스 검색
        grounding_tool = types.Tool(google_search=types.GoogleSearch())

        print("[Gemini] AI 리스크 분석 요청 중...")
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[grounding_tool],
                temperature=0.2,
            ),
        )

        # 응답 텍스트 추출
        analysis_text = response.text
        if not analysis_text:
            print("[Gemini] 응답이 비어있음")
            return None

        print(f"[Gemini] 응답 수신: {len(analysis_text)}자")

        # 마크다운 → 텍스트 변환
        analysis_clean = convert_markdown_to_text(analysis_text)

        # 리스크 섹션 포맷팅
        analysis_formatted = format_risk_sections(analysis_clean)

        # 최종 메시지 구성
        now = datetime.now(KST)
        lines = [
            '━━━━━━━━━━━━━━━━━━━',
            '      🤖 AI 리스크 체크',
            '━━━━━━━━━━━━━━━━━━━',
            f'📅 {now.strftime("%Y년 %m월 %d일")}',
            '',
            f'매수 후보 {len(stock_list)}종목의 최근 뉴스/이벤트를',
            'AI가 검색한 결과입니다. 참고용입니다!',
            '',
            analysis_formatted,
        ]

        print("[Gemini] AI 리스크 분석 완료")
        return '\n'.join(lines)

    except Exception as e:
        print(f"[Gemini] AI 분석 실패: {e}")
        return None


if __name__ == '__main__':
    # 테스트
    test_stocks = [
        {'ticker': '123330', 'name': '제닉', 'rank': 1, 'sector': 'K-뷰티/화장품'},
        {'ticker': '019180', 'name': '티에이치엔', 'rank': 2, 'sector': '자동차부품'},
        {'ticker': '402340', 'name': 'SK스퀘어', 'rank': 3, 'sector': '투자지주/AI반도체'},
    ]
    result = run_ai_analysis("테스트 메시지", test_stocks)
    if result:
        print("\n=== AI 분석 결과 ===")
        print(result)
    else:
        print("AI 분석 실패 또는 스킵")
