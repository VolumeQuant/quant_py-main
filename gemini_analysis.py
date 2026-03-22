"""
Gemini AI 포트폴리오 브리핑 모듈 — v3 정량 리스크 스캐너

"검색은 코드가, 분석은 AI가" 원칙:
- 코드가 위험 플래그를 팩트로 계산 → AI는 그 팩트만 해석
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
    종목별 위험 신호 계산 — 기술적 과열만

    가격 변동(급등/급락)은 경고하지 않음:
    - 4겹 검증 통과 종목의 가격 변동은 시장 움직임이지 개별 리스크가 아님
    - 급락은 매수 기회, 급등은 추세 확인
    """
    rsi = s.get('rsi', 50)

    flags = []

    # 0. 기술지표 데이터 누락
    if s.get('tech_missing'):
        flags.append("⚠️ 기술지표 확인 불가 (데이터 누락)")

    # 1. 과매수 (RSI >= 80) — 극단적 과열만 경고
    if rsi >= 80:
        flags.append(f"🔺 RSI {rsi:.0f}로 과매수 구간")

    return flags


def build_prompt(stock_list, base_date=None, market_context=None, market_index=None):
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
        action = market_context.get('action', '')
        market_block = f"""
[현재 시장 환경 — 시스템이 판단한 베타 위험]
행동 권장: {action}

→ 이 시장 환경을 종목 분석에 반영해줘.
  행동 권장에 '매도'나 '멈추'가 포함되면 더 엄격하게 봐줘.
  행동 권장에 '적극'이나 '평소대로'가 포함되면 긍정적으로 평가해줘.
"""

    # 시장 지수 factual anchoring (hallucination 방지)
    idx_block = ""
    if market_index:
        idx_parts = []
        if market_index.get('kospi_close'):
            idx_parts.append(f"코스피 {market_index['kospi_close']:,.0f}({market_index.get('kospi_chg', 0):+.2f}%)")
        if market_index.get('kosdaq_close'):
            idx_parts.append(f"코스닥 {market_index['kosdaq_close']:,.0f}({market_index.get('kosdaq_chg', 0):+.2f}%)")
        if idx_parts:
            idx_block = f"\n[당일 지수 마감 — 시스템이 계산한 팩트]\n{' / '.join(idx_parts)}\n→ 이 수치와 모순되는 내용을 쓰지 마.\n"

    prompt = f"""분석 기준일: {date_str}

아래는 한국주식 퀀트 시스템의 매수 후보 {stock_count}종목과 각 종목의 정량적 위험 신호야.
이 종목들은 밸류+퀄리티+성장+모멘텀 4팩터 멀티팩터로 선정된 거야.
네 역할: 위험 신호를 해석해서 "매수 시 주의할 종목"을 투자자에게 알려주는 거야.
{market_block}{idx_block}
[종목별 데이터 & 위험 신호 — 시스템이 계산한 팩트]
{signals_data}

[위험 신호 설명]
🔺 RSI 과매수 = RSI 80 이상, 극단적 과열 구간 (조정 가능성)

[출력 형식 — 반드시 지켜]
- 한국어, ~입니다 체. 번역투 금지. 자연스럽게.
- ⛔ "~답니다", "~랍니다", "~했답니다" 절대 사용 금지.
  반드시 "~입니다", "~했습니다", "~있습니다", "~됐습니다", "~보입니다"를 사용.
  예: "올랐답니다" → "올랐습니다", "기록했답니다" → "기록했습니다"
- ⛔ "~예요", "~해요", "~했어요", "~있어요" 체 사용 금지.
- 예시: "주가가 크게 하락했습니다", "조심할 필요가 있습니다", "아직은 양호한 상태입니다"
- 인사말, 서두, 맺음말 금지. 아래 섹션부터 바로 시작.
- 종목마다 문장 구조를 다르게 써. 같은 패턴 반복 금지.
- 트럼프는 2025년 1월 재취임한 현직 미국 대통령이야.
- 총 2000자 이내.

📰 시장 동향
{date_str} 한국 주식시장 마감 결과를 Google 검색해서 요약해줘.
- 2~3개 짧은 문단으로 나눠서 써. 한 문단은 2~3문장.
- 문단 사이에 빈 줄을 넣어서 가독성을 높여줘.
- 첫 문단: 시장 방향과 핵심 원인
- 둘째 문단: 업종·테마별 흐름
- (선택) 셋째 문단: 향후 주의할 변수
- {date_str} 시장의 핵심 이슈(원인, 테마, 업종별 흐름)를 구체적으로 써.
- 지수 수치(코스피 몇 포인트 등)는 반복하지 마. 위에 시스템이 이미 표시했어.
- "이번 주" 전체 요약은 하지 마. {date_str} 당일 마감에만 집중.
- [시제 규칙] 이 요약은 {date_str} 장 마감 이후에 작성하는 거야.
  마감 시점까지 이미 발표된 경제지표(FOMC, CPI, 고용 등)는 "결과"로 써.
  "향후 예정", "발표될 예정" 같은 미래형은 마감 이후 일정에만 써.

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
    # Step 3: 마크다운 → HTML 태그 (이탤릭 제거 v41)
    result = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', result)
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
    # Step 7: ~답니다/~랍니다 후처리 (Gemini가 프롬프트 무시할 때 방어)
    result = re.sub(r'했답니다', '했습니다', result)
    result = re.sub(r'랍니다', '입니다', result)
    result = re.sub(r'답니다', '습니다', result)
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


def run_ai_analysis(portfolio_message, stock_list, base_date=None, market_context=None, market_index=None):
    """
    Gemini 2.5 Flash AI 브리핑 실행 — v3 정량 리스크 스캐너

    "검색은 코드가, 분석은 AI가" 원칙:
    - 코드가 6가지 위험 플래그를 팩트로 계산
    - AI는 시장 동향 검색(1회) + 위험 신호 해석만 수행
    - Markdown → Telegram HTML 변환
    - market_context: 시장 환경 (행동 권장)

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
        client = genai.Client(api_key=api_key, http_options={'timeout': 180_000})
        prompt = build_prompt(stock_list, base_date=base_date, market_context=market_context, market_index=market_index)
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
            '후보 종목 중 주의할 점을 AI가 점검했습니다.',
            '',
            analysis_html + clean_section,
        ]

        print("[Gemini] AI 리스크 필터 완료")
        return '\n'.join(lines)

    except Exception as e:
        print(f"[Gemini] AI 분석 실패: {e}")
        return None


def build_final_picks_prompt(stock_list, weight_per_stock=None, base_date=None, market_context=None):
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
        line += f"\n   {', '.join(parts)}"
        stock_lines.append(line)

    stocks_data = '\n\n'.join(stock_lines)

    if base_date:
        date_str = f"{base_date[:4]}-{base_date[4:6]}-{base_date[6:]}"
    else:
        date_str = datetime.now(KST).strftime('%Y-%m-%d')

    # 시장 환경 블록
    market_block = ""
    if market_context:
        action = market_context.get('action', '')
        market_block = f"""
[시장 위험 상태]
행동 권장: {action}
→ 종목 설명에 시장 환경을 자연스럽게 반영해줘. 위험 높으면 "방어적", 안정적이면 "공격적" 톤으로.
"""

    return f"""분석 기준일: {date_str}

아래 {len(stock_list)}종목 각각의 실적/사업 성장 배경을 Google 검색해서 한 줄씩 써줘.
{market_block}
[종목]
{stocks_data}

[형식]
- 한국어, ~입니다 체. 번역투 금지. 자연스럽게.
- ⛔ "~답니다", "~랍니다", "~했답니다" 절대 사용 금지.
- ⛔ "~예요", "~해요", "~했어요", "~있어요" 체 사용 금지.
- 종목별: **종목명(티커)**
  비즈니스 매력 2~3문장, 120~180자 (가장 의미있는 수치를 맥락과 함께)
- 종목 사이에 [SEP]
- 맨 끝 별도 문구 없음

[규칙]
- 종목별 2단계로 써:
  1단계: 왜 실적이 좋은지 / 어떤 사업이 성장 중인지 (핵심 비즈니스 드라이버)
  2단계: {date_str} 전후 1~2주 이내 최신 뉴스가 검색되면 추가. 검색해도 최근 뉴스가 없으면 이 문장은 생략.
- 반드시 Google 검색 결과에 있는 실제 사실만 써. 추측하거나 지어내지 마.
- 예: "AI 반도체 수요 확대로 HBM 매출이 급증하고 있습니다"
  예: "전력 수요 폭증에 원전 재가동 기대감까지 더해졌습니다"
  예: "Fwd PER 5.5로 성장 대비 저평가입니다. 배당수익률 3.2%도 매력적입니다."
- 종목에 따라 가장 의미있는 지표를 골라서 맥락과 함께 설명해.
  반도체면 Fwd PER, 고배당주면 배당률, 성장주면 매출성장률.
- 단순히 "PER 낮음", "ROE 높음"처럼 숫자만 반복하지 마. 그 숫자 뒤의 사업적 이유를 써.
- "견고한 실적", "안정적 성장" 같은 뻔한 표현 금지. 구체적 사업/제품/고객사를 언급해.
- 날씨 아이콘(☀️🌤️🌧️ 등) 넣지 마.
- 주의/경고/유의 표현 금지. 긍정적 매력만.
- "선정", "포함", "선택" 같은 시스템 용어 금지.
- 서두/인사말/도입문 금지. 첫 번째 종목부터 바로 시작.
- 종목마다 다른 문장 구조로 써. 같은 패턴 반복 금지.
- 트럼프는 2025년 1월 재취임한 현직 미국 대통령이야."""


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
    # 이탤릭 제거 (v41)
    result = re.sub(r'\n*\[SEP\]\n*', '\n──────────────────\n', result)
    result = re.sub(r'#{1,3}\s*', '', result)
    result = re.sub(r'\n{3,}', '\n\n', result)
    result = re.sub(r'\n+──────────────────\n+', '\n──────────────────\n', result)
    # ~답니다/~랍니다 후처리
    result = re.sub(r'했답니다', '했습니다', result)
    result = re.sub(r'랍니다', '입니다', result)
    result = re.sub(r'답니다', '습니다', result)
    return result.strip()


def parse_narratives(html_text: str) -> dict:
    """AI 최종 추천 HTML에서 종목별 내러티브 1줄 추출

    Returns:
        {ticker: narrative_text} dict
    """
    narratives = {}
    if not html_text:
        return narratives

    # HTML 태그 제거 후 파싱
    clean = re.sub(r'<[^>]+>', '', html_text)

    # 패턴: "종목명(6자리티커)" 다음 줄이 내러티브
    # 또는 같은 줄에 이어서 나오는 경우
    parts = re.split(r'──────────────────', clean)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # 티커 6자리 추출
        ticker_match = re.search(r'\((\d{6})\)', part)
        if not ticker_match:
            continue
        ticker = ticker_match.group(1)

        # 티커가 포함된 줄 이후의 텍스트가 내러티브
        lines = [l.strip() for l in part.split('\n') if l.strip()]
        narrative = ''
        found_header = False
        for line in lines:
            if ticker in line:
                found_header = True
                continue
            if found_header and line:
                # 날씨 아이콘 제거
                narrative = re.sub(r'^[☀️🌤️☁️🌧️🔥⛈️❄️🌈]+\s*', '', line).strip()
                break

        if narrative:
            narratives[ticker] = narrative

    return narratives


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
        client = genai.Client(api_key=api_key, http_options={'timeout': 180_000})
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


def run_etf_matching(rankings_top5, base_date=None):
    """ETF 매칭 — Pro 2-step (검색→조합최적화)

    Step 1: Gemini Pro + Google Search — 종목별 ETF 검색
    Step 2: Gemini Pro — Greedy 알고리즘으로 최적 2~3 ETF 조합 선택

    Returns:
        str: 포맷된 ETF 추천 텍스트 (실패 시 None)
    """
    import time

    api_key = get_gemini_api_key()
    if not api_key:
        print("[ETF] GEMINI_API_KEY 미설정 — ETF 매칭 스킵")
        return None

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print("[ETF] google-genai 패키지 미설치 — ETF 매칭 스킵")
        return None

    n_stocks = len(rankings_top5)
    # 종목 텍스트 구성
    stock_text = '\n'.join(
        f'{r.get("composite_rank", r.get("rank", i+1))}. {r["name"]}({r["ticker"]}) {r.get("sector","")}'
        for i, r in enumerate(rankings_top5)
    )

    try:
        client = genai.Client(api_key=api_key, http_options={'timeout': 180_000})

        # ── Step 1: Pro + Google Search — 종목별 ETF 검색 ──
        prompt_step1 = f"""당신은 한국 ETF 전문가입니다.

아래 {n_stocks}종목 각각에 대해, 해당 종목을 구성종목으로 포함하는 한국 상장 테마/섹터 ETF를 찾아주세요.

{stock_text}

[규칙]
- KOSPI200, KOSPI100, KRX300 등 광범위 시장지수 ETF 제외
- 레버리지/인버스 ETF 제외
- "가치주" "배당" "고배당" "중소형" "코리아밸류업" 등 광범위 스타일 ETF 제외 (특정 산업/테마 ETF만)
- 각 종목별로 포함된 ETF 1~3개와 해당 ETF 내 비중(%)을 명시
- 찾을 수 없으면 "테마 ETF 미확인"으로 표기
- 반드시 Google 검색으로 확인
- 특히 위 종목 중 2개 이상을 동시에 포함하는 ETF가 있다면 반드시 명시 (커버리지 극대화에 중요)

[검색 키워드 힌트 — 이 키워드들로 Google 검색하세요]
- 반도체 대형: "반도체TOP10" "AI반도체TOP" "반도체" ETF
- 반도체 밸류체인: "SK하이닉스밸류체인" "반도체밸류체인" "반도체전공정" ETF (여러 반도체 종목을 동시 포함하는 ETF 탐색에 중요!)
- 반도체 소부장: "반도체소부장" "반도체핵심장비" "반도체핵심공정" "비메모리반도체" ETF
- 전력/에너지: "AI전력" "전력설비" "전력인프라" "전력기기" ETF
- 지주/밸류업: "지주회사" "5대그룹" ETF
- 조선/해운: "친환경조선" "조선해운" ETF
- 기타: "2차전지" "여행레저" "원자력" ETF

[출력 형식]
1. 종목명(티커): ETF명1(비중X%), ETF명2(비중Y%)
2. ...

마지막에 "복수 종목 포함 ETF" 섹션을 추가하여, 위 종목 중 2개 이상을 동시에 포함하는 ETF를 정리해주세요."""

        print("[ETF] Step 1: Pro 모델로 종목별 ETF 검색 중...")
        grounding_tool = types.Tool(google_search=types.GoogleSearch())
        step1_text = None
        for attempt in range(3):
            try:
                resp1 = client.models.generate_content(
                    model='gemini-2.5-pro',
                    contents=prompt_step1,
                    config=types.GenerateContentConfig(
                        tools=[grounding_tool],
                        temperature=0.1,
                    ),
                )
                step1_text = extract_text(resp1)
                if step1_text:
                    break
            except Exception as e:
                print(f"[ETF] Step 1 재시도 {attempt+1}/3: {e}")
                time.sleep(10 * (attempt + 1))

        if not step1_text:
            print("[ETF] Step 1 실패 — ETF 매칭 스킵")
            return None

        print(f"[ETF] Step 1 완료: {len(step1_text)}자")
        time.sleep(3)

        # ── Step 2: Pro — Greedy 최적 조합 선택 ──
        prompt_step2 = f"""당신은 한국 ETF 포트폴리오 전문가입니다.

[상위 {n_stocks}종목]
{stock_text}

[종목별 ETF 매핑 — Step 1 검색 결과]
{step1_text}

[과제]
위 매핑을 분석하여, {n_stocks}종목 커버리지를 극대화하는 ETF 2~3개 조합을 선택하세요.
(2개로 충분히 커버되면 2개만, 부족하면 3개까지)

[선택 기준 — 우선순위 순서대로]
1. 커버리지 극대화: {n_stocks}종목 중 최대한 많이 커버
2. 중복 커버 최소화: ETF끼리 같은 종목을 중복으로 커버하지 말고, 서로 다른 종목을 커버
3. ETF 내 해당 종목 비중이 높을수록 좋음
4. 테마 분산은 부차적 — 커버리지가 더 높다면 같은 카테고리에서 2개 ETF 선택 가능

[선택 방법 — 반드시 이 단계를 밟으세요]
1단계: Step 1 결과에서 모든 ETF와 해당 ETF가 커버하는 종목을 표로 정리
2단계: 가장 많은 종목을 커버하는 ETF를 1번으로 선택
   → "1번 ETF 선택: XXX → 커버됨: A, B / 남은 미커버: C, D, E"
3단계: 남은 미커버 종목 중 가장 많이 커버하는 ETF를 2번으로 선택
   → "2번 ETF 선택: YYY → 추가 커버: C / 남은 미커버: D, E"
   ⚠️ 이미 커버된 종목만 포함하는 ETF는 "추가 커버 0개"이므로 절대 선택하지 마세요!
4단계: 미커버 종목이 남아있으면 3번 선택, 없으면 2개로 종료

핵심 원칙: 각 단계에서 "새로 추가되는 종목 수"만 세세요. 이미 커버된 종목은 무시!

[출력 형식 — 분석 후 맨 마지막에 아래 형식으로 최종 결과를 써주세요]
① ETF명 (운용사)
→ 종목A(N위)·종목B(N위)

② ETF명 (운용사)
→ 종목C(N위)

(③은 필요한 경우에만)

커버: N/{n_stocks}
미포함: 종목D(N위)·종목E(N위)"""

        print("[ETF] Step 2: Pro 모델로 최적 조합 선택 중...")
        step2_text = None
        for attempt in range(3):
            try:
                resp2 = client.models.generate_content(
                    model='gemini-2.5-pro',
                    contents=prompt_step2,
                    config=types.GenerateContentConfig(
                        temperature=0.1,
                    ),
                )
                step2_text = extract_text(resp2)
                if step2_text:
                    break
            except Exception as e:
                print(f"[ETF] Step 2 재시도 {attempt+1}/3: {e}")
                time.sleep(10 * (attempt + 1))

        if not step2_text:
            print("[ETF] Step 2 실패 — ETF 매칭 스킵")
            return None

        print(f"[ETF] Step 2 완료: {len(step2_text)}자")

        # Step 2 결과에서 최종 추천 블록 추출 (① 부터)
        return _extract_etf_block(step2_text)

    except Exception as e:
        print(f"[ETF] ETF 매칭 실패: {e}")
        return None


def _extract_etf_block(text):
    """Step 2 출력에서 최종 ETF 추천 블록 추출 (① ~ 미포함)"""
    lines = text.split('\n')

    # 마지막 ① 위치 찾기 (분석 과정에도 ①이 나올 수 있으므로 마지막 것 사용)
    start_idx = None
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip().startswith('①'):
            start_idx = i
            break

    if start_idx is None:
        print("[ETF] ① 블록 미발견 — 전체 텍스트 반환")
        return text

    # ① 부터 끝까지 추출, 불필요한 후행 빈줄 제거
    result_lines = []
    for line in lines[start_idx:]:
        stripped = line.strip()
        # 마크다운 볼드 제거
        stripped = re.sub(r'\*\*(.+?)\*\*', r'\1', stripped)
        # 불릿 포인트 정리
        stripped = stripped.lstrip('* ')
        result_lines.append(stripped)

    # 후행 빈줄 제거
    while result_lines and not result_lines[-1].strip():
        result_lines.pop()

    return '\n'.join(result_lines)


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
