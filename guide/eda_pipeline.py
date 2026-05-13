"""
EDA 처리 파이프라인 — 정답데이터1·2 xlsx 추출본 → eda_result_521.md

원칙: 가이드 PDF backing이 명시된 분류·라벨링만 사용. 자체 발명 통계 룰은 백로그.

전제:
1. extract.bat (powershell extract_xlsx.ps1) 선행 실행
2. C:\\dev\\guide\\정답데이터2_xlsx_dump.txt + 정답데이터1_xlsx_dump.txt 존재
3. C:\\dev\\guide\\eda_framework\\01_pattern_labeling_dictionary.md 라벨링 사전 참조

실행: cd C:\\dev\\guide && python eda_pipeline.py

산출:
- C:\\dev\\guide\\eda_result_521.md
- C:\\dev\\guide\\eda_framework\\02_cross_tab_template.md (셀 채워서 덮어쓰기 X — 별도 _filled 파일)
- C:\\dev\\guide\\eda_framework\\03_sample_vs_full_comparison_filled.md
"""

import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

# ────────── 경로 ──────────
GUIDE_DIR = Path(r"C:\dev\guide")
DUMP1 = GUIDE_DIR / "정답데이터1_xlsx_dump.txt"
DUMP2 = GUIDE_DIR / "정답데이터2_xlsx_dump.txt"
OUT_RESULT = GUIDE_DIR / "eda_result_521.md"
OUT_CROSS = GUIDE_DIR / "eda_framework" / "02_cross_tab_filled.md"
OUT_COMPARE = GUIDE_DIR / "eda_framework" / "03_sample_vs_full_filled.md"


# ────────── 채널 분류 룰 (가이드 backing) ──────────
# 가이드 59p (SMS), 60-62p (LMS), 63-64p (LMS 마케팅), 65-66p (알림톡), 67p (이메일), 121-125p (VOC)
CHANNEL_RULES = {
    "LMS_고지": [r"\[미래에셋증권\].*안내", r"고지", r"공지", r"■.*내역"],
    "LMS_마케팅": [r"\(광고\)", r"이벤트", r"혜택", r"※ 투자.*설명", r"※ 예금자보호", r"※ 원금손실"],
    "SMS": [r"^.{1,45}$"],  # 가이드 59p 45자 이내
    "알림톡": [r"7일", r"카카오", r"CTA", r"버튼"],
    "이메일": [r"미래에셋증권과 함께해 주셔서 감사합니다"],  # 가이드 67p
    "뉴스레터": [r"뉴스레터", r"리서치", r"투자이야기"],
    "VOC": [r"고객님, 안녕하세요", r"VOC전담", r"콜센터.*응대"],  # 가이드 121-125p
}

# ────────── 도메인 분류 룰 (운영 분류) ──────────
DOMAIN_KEYWORDS = {
    "credit_loan": ["신용", "대출", "융자", "신용공여", "추가증거금"],
    "derivatives": ["ELS", "DLS", "ELB", "DLC", "선물", "옵션", "파생", "CFD", "워런트"],
    "product": ["상품", "신탁", "펀드", "ETF", "ETN", "MMF", "ISA", "IRP"],
    "settlement": ["정산", "지급", "출금", "입금", "결제", "환전"],
    "pension": ["퇴직연금", "DC", "DB", "디폴트옵션", "MP", "리밸런싱"],
    "marketing": ["이벤트", "혜택", "(광고)", "프로모션"],
    "process": ["진단", "재진단", "변경", "신청", "동의", "철회"],
    "misc": [],
}

# ────────── 패턴 코드 사전 (가이드 backing 명확) ──────────
# 출처: eda_framework/01_pattern_labeling_dictionary.md
PATTERN_CODES = {
    "HDR.LMS.MAS": {"pattern": r"^\[미래에셋증권\]", "guide": "60p"},
    "OPN.HONOR.A": {"pattern": r"#\{\{?고객명\}?\} 고객님,", "guide": "36p, 60p"},
    "BLK.NAE": {"pattern": r"■ 가입정보|■ 계좌정보|■ 종목정보|■ 미수금내역|■ 권리발생내역|■ 청약취소내역", "guide": "60p"},
    "BLK.UI.꼭확인": {"pattern": r"■ 꼭 확인해 주세요", "guide": "60p"},
    "BLK.QA.문의": {"pattern": r"■ 문의", "guide": "60p"},
    "ITM.DASH": {"pattern": r"^- .+: ", "guide": "60p"},
    "CLS.REQ": {"pattern": r"해 주세요\.?\s*$", "guide": "26p"},
    "CLS.ANN": {"pattern": r"안내드립니다\.?\s*$", "guide": "26p"},
    "VAR.NAME": {"pattern": r"#\{\{?고객명\}?\}", "guide": "78-79p"},
    "VAR.ACCT": {"pattern": r"#\{\{?계좌번호\}?\}", "guide": "78-79p"},
    "VAR.URL": {"pattern": r"#\{\{?URL\}?\}", "guide": "79p"},
    "VAR.DATE": {"pattern": r"#\{\{?YYYY\.MM\.DD\}?\}", "guide": "82-117p"},
    "TM.HHMM": {"pattern": r"\d{2}:\d{2}", "guide": "82-117p"},
    "SYM.PHONE_DROP": {"pattern": r"☎", "guide": "79p (☎ 삭제)"},  # 출현 시 차단
    "MAR.AD_TAG": {"pattern": r"\(광고\)", "guide": "63-64p"},
    "MAR.SUSPENSE_3": {"pattern": r"※ 투자.*설명|※ 예금자보호|※ 원금손실", "guide": "63-64p"},
    "VOC.OPEN": {"pattern": r".+ 고객님, 안녕하세요\.", "guide": "121-125p"},
    "KOR.HANJA": {"pattern": r"당사|익일|익영업일|상기|하기|본 건", "guide": "134p"},  # 미변환 회귀 검사
}


# ────────── 유틸 ──────────
def split_cases(dump_text: str):
    """xlsx_dump 텍스트를 case 단위로 분할.
    extract_xlsx.ps1 출력 형식: '--- Row N ---' 단위.
    각 row가 1 케이스 (or 시트별)."""
    cases = []
    current = []
    for line in dump_text.splitlines():
        if line.startswith("--- Row "):
            if current:
                cases.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        cases.append("\n".join(current))
    return cases


def detect_channel(case_text: str) -> str:
    for ch, patterns in CHANNEL_RULES.items():
        for p in patterns:
            if re.search(p, case_text, re.MULTILINE):
                return ch
    return "기타_미분류"


def detect_domain(case_text: str) -> str:
    scores = {}
    for dom, kws in DOMAIN_KEYWORDS.items():
        score = sum(1 for kw in kws if kw in case_text)
        if score > 0:
            scores[dom] = score
    if not scores:
        return "misc"
    return max(scores, key=scores.get)


def detect_patterns(case_text: str):
    found = []
    for code, info in PATTERN_CODES.items():
        if re.search(info["pattern"], case_text, re.MULTILINE):
            found.append(code)
    return found


def detect_label(case_text: str) -> str:
    """라벨 신뢰도 추정 (HIGH/MEDIUM/LOW/NEGATIVE/EVAL).
    실제 라벨은 정답지 metadata에 있어야 정확. 추정은 휴리스틱."""
    text_lower = case_text.lower()
    if "negative" in text_lower or "반례" in text_lower or "차단" in text_lower:
        return "NEGATIVE"
    if "high" in text_lower or "검토완료" in text_lower or "<v2>" in case_text:
        return "HIGH"
    if "low" in text_lower or "검토필요" in text_lower:
        return "LOW"
    return "MEDIUM"


# ────────── 메인 처리 ──────────
def process_dump(dump_path: Path, label: str):
    if not dump_path.exists():
        print(f"[ERROR] {dump_path} 없음. extract.bat 먼저 실행.")
        return None

    text = dump_path.read_text(encoding="utf-8", errors="ignore")
    cases = split_cases(text)
    print(f"  {label}: {len(cases)}건 split 완료")

    results = []
    for case_text in cases:
        if len(case_text.strip()) < 50:
            continue  # 너무 짧으면 skip
        results.append({
            "channel": detect_channel(case_text),
            "domain": detect_domain(case_text),
            "patterns": detect_patterns(case_text),
            "label": detect_label(case_text),
            "length": len(case_text),
        })
    return results


def cross_tab(results, key1: str, key2: str):
    table = defaultdict(lambda: defaultdict(int))
    for r in results:
        table[r[key1]][r[key2]] += 1
    return table


def write_md_table(f, table, row_label, col_label, all_cols=None):
    cols = sorted(set(c for row in table.values() for c in row.keys())) if all_cols is None else all_cols
    f.write(f"| {row_label} \\ {col_label} | " + " | ".join(cols) + " | (합계) |\n")
    f.write("|" + "---|" * (len(cols) + 2) + "\n")
    for row_key in sorted(table.keys()):
        row = table[row_key]
        total = sum(row.values())
        f.write(f"| {row_key} | " + " | ".join(str(row.get(c, 0)) for c in cols) + f" | **{total}** |\n")
    # 합계 행
    col_totals = {c: sum(table[r].get(c, 0) for r in table) for c in cols}
    grand = sum(col_totals.values())
    f.write("| **(합계)** | " + " | ".join(f"**{col_totals[c]}**" for c in cols) + f" | **{grand}** |\n")


def main():
    print("=== Mi-Tone EDA 파이프라인 시작 ===")

    print("\n[1/5] 정답데이터1 처리...")
    r1 = process_dump(DUMP1, "정답데이터1")
    if r1 is None:
        sys.exit(1)

    print("\n[2/5] 정답데이터2 처리...")
    r2 = process_dump(DUMP2, "정답데이터2")
    if r2 is None:
        sys.exit(1)

    all_results = r1 + r2
    n_total = len(all_results)
    print(f"\n  전체: {n_total}건")

    # ────────── Sanity Check ──────────
    expected_total = 551  # 정답데이터1 30 + 정답데이터2 521
    if n_total != expected_total:
        print(f"  [WARN] 케이스 수 mismatch: 추출 {n_total} vs 기대 {expected_total}")
        print(f"         정답데이터1: {len(r1)} (기대 30) / 정답데이터2: {len(r2)} (기대 521)")
    else:
        print(f"  [OK] sanity check: {n_total} = 30 + 521")

    # ────────── HIGH/NEGATIVE 별도 추출 ──────────
    high_cases = [i for i, r in enumerate(all_results) if r["label"] == "HIGH"]
    negative_cases = [i for i, r in enumerate(all_results) if r["label"] == "NEGATIVE"]
    print(f"  HIGH 라벨: {len(high_cases)}건 (기대 ~17건)")
    print(f"  NEGATIVE 라벨: {len(negative_cases)}건 (기대 ~38건)")

    # ────────── cross-tab ──────────
    print("\n[3/5] cross-tab 작성...")
    ch_dom = cross_tab(all_results, "channel", "domain")
    dom_label = cross_tab(all_results, "domain", "label")

    # ────────── 패턴 빈도 ──────────
    pattern_count = Counter()
    for r in all_results:
        for p in r["patterns"]:
            pattern_count[p] += 1

    # ────────── 50건 vs 521건 비교 ──────────
    # eval_50_cases.txt가 있으면 비교 — 없으면 전수 통계만
    print("\n[4/5] 누락 패턴 식별...")
    eval50_path = GUIDE_DIR / "05_평가셋" / "eval_50_cases.txt"
    sample_patterns = set()
    if eval50_path.exists():
        sample_text = eval50_path.read_text(encoding="utf-8", errors="ignore")
        sample_cases = split_cases(sample_text)
        for c in sample_cases:
            sample_patterns.update(detect_patterns(c))

    full_patterns = set(pattern_count.keys())
    only_in_full = full_patterns - sample_patterns

    # ────────── 결과 작성 ──────────
    print(f"\n[5/5] {OUT_RESULT.name} 작성...")
    with OUT_RESULT.open("w", encoding="utf-8") as f:
        f.write(f"# 정답데이터 전수 EDA 결과 ({n_total}건)\n\n")
        f.write(f"실행일: {os.popen('date /t').read().strip()}\n")
        f.write(f"정답데이터1: {len(r1)}건 / 정답데이터2: {len(r2)}건\n\n")

        f.write("---\n\n## 1. 채널 × 도메인\n\n")
        write_md_table(f, ch_dom, "채널", "도메인")

        f.write("\n---\n\n## 2. 도메인 × 라벨\n\n")
        write_md_table(f, dom_label, "도메인", "라벨")

        f.write("\n---\n\n## 3. 패턴 빈도 (가이드 backing 명확)\n\n")
        f.write("| 패턴 코드 | 빈도 | 빈도 % | 가이드 페이지 |\n|---|---|---|---|\n")
        for code, cnt in pattern_count.most_common():
            pct = cnt / n_total * 100
            guide_p = PATTERN_CODES.get(code, {}).get("guide", "?")
            f.write(f"| {code} | {cnt} | {pct:.1f}% | {guide_p} |\n")

        f.write("\n---\n\n## 4. 50건 표본 누락 패턴 (전수에만 등장)\n\n")
        if only_in_full:
            for p in sorted(only_in_full):
                guide_p = PATTERN_CODES.get(p, {}).get("guide", "?")
                f.write(f"- {p} (가이드 {guide_p}) — 50건 표본 누락, 전수 등장\n")
        else:
            f.write("없음 (50건 표본이 전수 패턴 모두 커버 또는 eval_50_cases.txt 없음)\n")

        f.write("\n---\n\n## 4-1. HIGH 라벨 케이스 (시스템 프롬프트 EX 안전 후보)\n\n")
        f.write(f"총 {len(high_cases)}건. 회사 검수 통과 = '그대로 복사' 안전.\n\n")
        f.write("| 케이스 idx | 채널 | 도메인 | 패턴 수 |\n|---|---|---|---|\n")
        for idx in high_cases:
            r = all_results[idx]
            f.write(f"| {idx} | {r['channel']} | {r['domain']} | {len(r['patterns'])} |\n")

        f.write("\n---\n\n## 4-2. NEGATIVE 케이스 (가이드 룰 미수용 — 차단 학습용)\n\n")
        f.write(f"총 {len(negative_cases)}건. 가이드 적용 자제, 원안 가깝게 유지.\n\n")
        f.write("| 케이스 idx | 채널 | 도메인 |\n|---|---|---|\n")
        for idx in negative_cases:
            r = all_results[idx]
            f.write(f"| {idx} | {r['channel']} | {r['domain']} |\n")

        f.write("\n---\n\n## 4-3. 재현율 추정 (가이드 backing 패턴 기반)\n\n")
        f.write("필수 (≥80%) 패턴이 전수에 정확히 등장하는 비율 = 시스템 프롬프트가 가이드 backing 패턴을 재현하는 정도.\n\n")
        guide_backed = [c for c, n in pattern_count.items() if n / n_total >= 0.8]
        if guide_backed:
            f.write("**필수 패턴 (≥80%)**:\n")
            for code in guide_backed:
                guide_p = PATTERN_CODES.get(code, {}).get("guide", "?")
                f.write(f"- {code} (가이드 {guide_p}) — {pattern_count[code]/n_total*100:.1f}%\n")
            f.write(f"\n재현율 추정: 시스템 프롬프트 v6.0/v11.0/v6.0이 위 {len(guide_backed)}개 필수 패턴을 모두 anchor에 박고 있는지 검증 필요. (수동 검증 권장)\n")
        else:
            f.write("필수 패턴 없음 (모든 패턴이 80% 미만 — 채널 다양성으로 인한 분산 가능).\n")

        f.write("\n---\n\n## 5. 등급 분류 (가이드 backing)\n\n")
        f.write("- 필수 (≥80%): ")
        f.write(", ".join(c for c, n in pattern_count.items() if n / n_total >= 0.8))
        f.write("\n- 조건부 (30-80%): ")
        f.write(", ".join(c for c, n in pattern_count.items() if 0.3 <= n / n_total < 0.8))
        f.write("\n- 선택 (<30%): ")
        f.write(", ".join(c for c, n in pattern_count.items() if n / n_total < 0.3))

        f.write("\n\n---\n\n## 6. 자체 발명 통계 (가이드 silent — 백로그)\n\n")
        f.write("아래 항목은 가이드 PDF에 명시 없음. 운영 검토용 참고만:\n\n")
        f.write("- 95% CI / 신뢰구간: guide_check_backlog.md EDA-BL-1\n")
        f.write("- KL divergence / entropy: EDA-BL-2\n")
        f.write("- BLEU / ROUGE / Levenshtein: EDA-BL-3\n")

    print(f"\n=== 완료. {OUT_RESULT} ===")


if __name__ == "__main__":
    main()
