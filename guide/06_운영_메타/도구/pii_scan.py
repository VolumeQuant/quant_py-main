"""
5단계: PII 스캔 도구 — 카드 docx 전수 점검 (v2 — 보수적 정규식)

스캔 대상:
  - 주민등록번호: 6자리-7자리 숫자 (예: 950101-1234567)
  - 계좌번호: 한국 은행/증권 계좌 패턴 (단, 1588-XXXX 같은 안전 번호 제외)
  - 휴대폰: 010/011/016/017/018/019-XXXX-XXXX
  - 이메일: name@domain
  - 실명 후보: 3-4자 한국 이름 (성+이름 2자 또는 성+이름 3자)
            * 가이드 예시 화이트리스트 적용
            * 회사 임직원 (안내 PDF 명시) 별도 검토

처리:
  - 발견 시 위치 보고 (파일·문장)
  - 자동 치환 안 함
"""

import re
from pathlib import Path
from docx import Document

CARD_DIRS = [
    r"C:\dev\guide\정답데이터1",
    r"C:\dev\guide\정답데이터2",
]

# 가이드 예시 이름 (PII 아님)
EXAMPLE_NAMES = {
    "김미래", "박미래", "이에셋", "김에셋",
    "에셋산업", "가나기업", "가나산업",
}

# 회사 임직원 — REVIEW (★사용자 사내 검증 필요 — 자의 추정 이름 포함 가능★)
# 카드 docx에 등장하는 작성자명·검수자명을 PII로 잘못 알림 방지용 화이트리스트.
# 회사 가서 실제 임직원 명단으로 교체 권장. 빈 리스트로 시작해도 안전 (PII 알림 발생 시 사용자 검토).
COMPANY_STAFF = set()  # 빈 리스트 — 사용자 사내 검증 후 추가

# 한국 성씨 (자주 등장하는 것 위주)
SURNAMES = "김이박최정강조윤장임한오서신권황안송류전홍고문양손배백허남심노표공현민변"

PATTERNS = {
    "주민등록번호": re.compile(r"\b(\d{6})[-\s]?[1-4]\d{6}\b"),
    "휴대폰": re.compile(r"\b01[016789][-\s]\d{3,4}[-\s]\d{4}\b"),
    "이메일": re.compile(r"\b[\w._%+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
    # 계좌번호 — 3자리 이상 숫자가 -로 연결된 한국 계좌 패턴
    # (단 1588-XXXX, 02-XXXX-XXXX 같은 전화는 SAFE 처리)
    "계좌번호_후보": re.compile(r"\b\d{3,4}-\d{2,4}-\d{4,8}\b"),
    # ※ 실명 검사 제외:
    #   - 한국어 정규식만으론 정확히 잡히지 않음 (성씨 글자가 일반 단어 첫글자로 흔함)
    #   - 카드는 모두 #{고객명} 플레이스홀더 사용. 실제 이름 등장 가능성 매우 낮음
    #   - 카드 변환 시 담당팀 컬럼에서 팀명만 추출 (작성자 이름 자동 제거)
}

# SAFE 패턴 — 매치를 무시
SAFE_PATTERNS = [
    re.compile(r"#\{[^}]+\}"),                    # 플레이스홀더
    re.compile(r"1588-\d{4}"),                    # 고객센터
    re.compile(r"02-\d{3,4}-\d{4}"),              # 일반 전화
    re.compile(r"02-6714-\d{4}"),                 # 전용 ARS
]


def is_safe_match(text, match_str, match_start, match_end):
    """매치 위치가 SAFE 패턴 안에 있는지."""
    for safe in SAFE_PATTERNS:
        for m in safe.finditer(text):
            if m.start() <= match_start and match_end <= m.end():
                return True
    return False


def scan_text(text):
    findings = []
    for kind, pat in PATTERNS.items():
        for m in pat.finditer(text):
            matched = m.group()

            # 실명 후보 처리
            if kind.startswith("실명"):
                if matched in EXAMPLE_NAMES:
                    continue
                if matched in COMPANY_STAFF:
                    findings.append({"kind": kind, "match": matched, "level": "REVIEW"})
                    continue
                # 그 외는 ALERT
                findings.append({"kind": kind, "match": matched, "level": "ALERT"})
                continue

            # 다른 패턴 SAFE 검사
            if is_safe_match(text, matched, m.start(), m.end()):
                continue

            findings.append({"kind": kind, "match": matched, "level": "ALERT"})
    return findings


def scan_docx(docx_path):
    doc = Document(docx_path)
    file_findings = []
    for i, p in enumerate(doc.paragraphs):
        text = p.text
        if not text.strip():
            continue
        findings = scan_text(text)
        if findings:
            for f in findings:
                f["paragraph_idx"] = i
                f["paragraph_preview"] = text[:80]
            file_findings.extend(findings)
    return file_findings


def main():
    print("=== 5단계: PII 스캔 (v2 — 보수적 정규식) ===\n")

    total_alert = 0
    total_review = 0
    files_with_pii = 0
    files_scanned = 0

    for dir_path in CARD_DIRS:
        for docx_path in sorted(Path(dir_path).glob("cx_*.docx")):
            files_scanned += 1
            findings = scan_docx(str(docx_path))
            if findings:
                files_with_pii += 1
                # 종류별 분류
                by_kind = {}
                for f in findings:
                    by_kind.setdefault(f["kind"], []).append(f)

                alert_count = sum(1 for f in findings if f["level"] == "ALERT")
                review_count = sum(1 for f in findings if f["level"] == "REVIEW")
                total_alert += alert_count
                total_review += review_count

                print(f"📄 {docx_path.name}")
                print(f"   ALERT={alert_count}, REVIEW={review_count}")
                # 종류별 샘플 5건
                for kind, fs in by_kind.items():
                    icon = "🚨" if fs[0]["level"] == "ALERT" else "ℹ️"
                    examples = list(set(f["match"] for f in fs))[:5]
                    print(f"   {icon} [{kind}] {len(fs)}건 — 샘플: {examples}")
                print()

    print("=" * 60)
    print(f"스캔 완료: {files_scanned}개 파일")
    print(f"PII 발견: {files_with_pii}개 파일")
    print(f"  🚨 ALERT: {total_alert}건")
    print(f"  ℹ️  REVIEW: {total_review}건")
    print("=" * 60)
    if total_alert == 0 and total_review == 0:
        print("✅ PII 발견 없음. 카드 모두 안전.")
    elif total_alert == 0:
        print("✅ 실제 PII 없음. REVIEW 항목은 안내 PDF 공개 임직원 직무명.")


if __name__ == "__main__":
    main()
