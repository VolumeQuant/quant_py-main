# -*- coding: utf-8 -*-
"""leave-one-superwinner-out 검증 도구 (US v83.2 교훈 코드화)

US v83.2 교훈: 71일 단일 표본 + 2슬롯 80/20에서 boost edge가 전부 MU 한 종목 →
MU 제외 시 동전던지기. **변경 평가 시 반드시 dominant winner 제외 후 robustness 확인.**

KR EPS adapt: 60일 누적 후 변경 검증 시 사용.

실행:
  python kr_eps_momentum/research/leave_one_out.py --change <변경명> --metric <지표>

흐름:
1. 전체 데이터로 baseline vs 변경 BT
2. 최대 수익 단일 종목 (dominant winner) 식별
3. 그 종목 제외하고 BT 재실행
4. 변경 effect가 robust한지 (단일 종목 의존 X) 판정
"""
import argparse, sqlite3, sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

DB = Path(__file__).resolve().parent.parent / 'eps_momentum_data_kr.db'


def get_top_winner(conn, date_range=None):
    """기간 내 dominant winner (단일종목 가장 큰 수익 기여) 식별."""
    # paper_trade 또는 portfolio_log 테이블에서 종목별 누적 수익 sum
    # KR EPS 60일 누적 후 구현 (현재 데이터 부족)
    c = conn.cursor()
    try:
        rows = c.execute(
            "SELECT ticker, SUM(return_pct) as total FROM portfolio_log "
            "WHERE action='exit' GROUP BY ticker ORDER BY total DESC LIMIT 5"
        ).fetchall()
        if rows:
            print(f'Top 5 winners (기간 누적 수익률 sum):')
            for tk, tot in rows: print(f'  {tk}: {tot:+.1f}%')
            return rows[0][0]
    except sqlite3.OperationalError:
        pass
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--change', help='변경 이름 (예: MIN_NTM_500)')
    ap.add_argument('--exclude', help='제외할 ticker (자동 선택 시 생략)')
    args = ap.parse_args()
    if not DB.exists():
        print(f'DB 없음: {DB}'); return 1
    conn = sqlite3.connect(DB)
    print(f'=== leave-one-superwinner-out 검증 ===')
    print(f'변경: {args.change or "(unspecified)"}')
    top = args.exclude or get_top_winner(conn)
    if not top:
        print('Dominant winner 식별 실패 — paper_trade 누적 60일 후 재실행 권장')
        return 0
    print(f'\nDominant winner: {top}')
    print(f'\n검증 단계 (TODO 60일 누적 후 구현):')
    print(f'  1) 전체 데이터 baseline vs 변경 BT 결과')
    print(f'  2) {top} 제외하고 BT 재실행')
    print(f'  3) Δ Cal/MDD 변동 확인')
    print(f'  4) {top} 제외 시 변경 edge 사라지면 = single-stock 착시 → reject')
    print(f'  5) {top} 제외해도 변경 edge 유지되면 = robust → accept')
    conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
