# -*- coding: utf-8 -*-
"""Multistart BT framework (US v80.6 6시작일 표준화 교훈 코드화)

US v80.6 교훈: 33시작일 평균이 짧은 기간 시작일(5거래일짜리)로 흐려져 잘못된 결론.
6시작일 multistart (50거래일+ 보장)로 +18%p 알파 일관 확인.

KR EPS adapt: 60일 누적 후 BT 시 6시작일 기본 패턴.

실행:
  python kr_eps_momentum/research/multistart_bt.py --change <변경명>

흐름:
1. 60+ 누적 거래일 확인
2. 6개 시작일 선택 (간격 10일 균등 분포)
3. 각 시작일에서 baseline vs 변경 BT
4. 6/6 일관 양수 → robust, 변동 큼 → noise
"""
import argparse, sqlite3, sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

DB = Path(__file__).resolve().parent.parent / 'eps_momentum_data_kr.db'


def get_trading_dates(conn):
    c = conn.cursor()
    return [r[0] for r in c.execute(
        'SELECT DISTINCT date FROM ntm_screening ORDER BY date'
    ).fetchall()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--change', help='변경 이름')
    ap.add_argument('--n_starts', type=int, default=6, help='시작일 수 (기본 6)')
    ap.add_argument('--min_days', type=int, default=50, help='시작일당 최소 일수')
    args = ap.parse_args()
    if not DB.exists():
        print(f'DB 없음: {DB}'); return 1
    conn = sqlite3.connect(DB)
    dates = get_trading_dates(conn)
    print(f'=== Multistart BT (US v80.6 표준) ===')
    print(f'변경: {args.change or "(unspecified)"}')
    print(f'누적 데이터: {len(dates)} 거래일')
    if len(dates) < args.min_days + args.n_starts * 10:
        print(f'⚠️ 데이터 부족: {args.n_starts}시작일 × {args.min_days}일 보장 필요')
        print(f'   누적 {len(dates)}일 < {args.min_days + args.n_starts * 10}일')
        print(f'   60일 누적 (~8월 초) 후 재실행 권장')
        return 0
    # 균등 분포로 시작일 선택
    step = (len(dates) - args.min_days) // args.n_starts
    start_idxs = [i * step for i in range(args.n_starts)]
    print(f'\n시작일 {args.n_starts}개 (균등 분포):')
    for i, idx in enumerate(start_idxs):
        end_idx = idx + args.min_days
        print(f'  {i+1}: {dates[idx]} ~ {dates[end_idx-1]} ({args.min_days}일)')
    print(f'\nTODO: 각 시작일에서 baseline vs 변경 BT 실행 + 결과 비교')
    print(f'  - 6/6 모두 양수 → robust → accept')
    print(f'  - 변동 큼/일부 음수 → noise → reject')
    conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
