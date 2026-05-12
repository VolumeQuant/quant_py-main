"""Step 3 완료 후 Step 4~11 자동 진행 (DART 호출 X 단계만).

순서:
  1. Step 4: verify_after_refetch.py (Step 3 결과 검증)
  2. Step 8 통합 재수집: 34종목 (additional 10 + extra 24 - 중복)
  3. Step 4 재실행 (전체 검증)
  4. Step 9: regenerate_all_v80.py (state 재생성, ~28분)
  5. Step 10: compare_optf_bt.py (BT 검증)
  6. Step 11: 5/11 ranking 재생성 + OLD vs NEW 비교

사용자 결정 필요한 단계 (Step 12 commit + Step 13 스케줄러) 제외.
"""
import os, sys, subprocess, time, json
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

PYTHON = sys.executable
PROJECT = Path(__file__).parent

def run_step(name, cmd, env=None, timeout=3600):
    print(f'\n{"="*60}\n[{name}] 시작\n{"="*60}', flush=True)
    t0 = time.time()
    merged_env = {**os.environ, **(env or {})}
    r = subprocess.run(cmd, cwd=str(PROJECT), env=merged_env,
                       capture_output=True, text=True, encoding='utf-8', errors='replace',
                       timeout=timeout)
    elapsed = time.time() - t0
    print(r.stdout[-3000:] if r.stdout else '(no stdout)')
    if r.returncode != 0:
        print(f'STDERR: {r.stderr[-500:]}')
    print(f'\n[{name}] rc={r.returncode} ({elapsed/60:.1f}분)', flush=True)
    return r.returncode

def main():
    # Step 4: verify
    rc4 = run_step('Step 4: verify_after_refetch (Step 3 결과)',
                   [PYTHON, '-u', 'verify_after_refetch.py'], timeout=600)
    # rc 0=통과 1=경고 2=치명 — 1까지 진행 OK
    if rc4 == 2:
        print('\n❌ Step 4 치명적 실패 — 작업 중단. 수동 검토 필요.')
        return

    # Step 8 통합 재수집: 34종목
    rc8 = run_step('Step 8 통합: 34종목 추가 재수집',
                   [PYTHON, '-u', 'refetch_serial.py'],
                   env={'BAD_LIST': str(PROJECT / 'bad_tickers_step3_additional.txt')},
                   timeout=3600)
    if rc8 != 0:
        print('\n⚠️ Step 8 일부 실패 — refetch_failed.txt 확인. 계속 진행.')

    # Step 4 재실행 (전체 통합 검증)
    rc4b = run_step('Step 4 재실행 (전체 검증)',
                    [PYTHON, '-u', 'verify_after_refetch.py'], timeout=600)
    if rc4b == 2:
        print('\n❌ 전체 검증 치명적 — 작업 중단.')
        return

    # Step 9: state 재생성 (~35분, 내부 subprocess 2병렬 × 2순차)
    rc9 = run_step('Step 9: state 7.8년 재생성',
                   [PYTHON, '-u', 'backtest/regenerate_all_v80.py'], timeout=4200)
    if rc9 != 0:
        print('\n❌ Step 9 실패 — 작업 중단.')
        return

    # Step 10: BT 검증
    rc10 = run_step('Step 10: BT 검증',
                    [PYTHON, '-u', 'backtest/compare_optf_bt.py'], timeout=600)

    # Step 11: 5/11 ranking 재생성 (state_verify/에 단독 생성)
    state_verify = PROJECT / 'state_verify'
    state_verify.mkdir(exist_ok=True)
    boost_env = {
        'FACTOR_V_W': '0.15', 'FACTOR_Q_W': '0.00', 'FACTOR_G_W': '0.55', 'FACTOR_M_W': '0.30',
        'G_SUB1': 'rev_z', 'G_SUB2': 'oca_z', 'G_REVENUE_WEIGHT': '0.6', 'MOM_PERIOD': '12m',
    }
    rc11 = run_step('Step 11: 5/11 ranking 단독 재생성 (state_verify/)',
                    [PYTHON, '-u', 'backtest/fast_generate_rankings_v2.py',
                     '20260511', '20260511', '--state-dir=state_verify'],
                    env=boost_env, timeout=600)

    # 비교
    if rc11 == 0:
        print('\n=== 5/11 ranking OLD vs NEW 비교 ===')
        try:
            with open('state/ranking_20260511.json', encoding='utf-8') as f:
                o = json.load(f).get('rankings', [])
            with open('state_verify/ranking_20260511.json', encoding='utf-8') as f:
                n = json.load(f).get('rankings', [])
            print(f'OLD Top 10:')
            for r in sorted(o, key=lambda x: x.get('composite_rank', 999))[:10]:
                print(f'  {r["composite_rank"]}위 {r["name"]}({r["ticker"]}) [{r.get("sector")}]')
            print(f'\nNEW Top 10:')
            for r in sorted(n, key=lambda x: x.get('composite_rank', 999))[:10]:
                print(f'  {r["composite_rank"]}위 {r["name"]}({r["ticker"]}) [{r.get("sector")}]')
        except Exception as e:
            print(f'비교 오류: {e}')

    print(f'\n{"="*60}\n자동 진행 완료 — 다음 사용자 확인 후 Step 12 commit + Step 13 스케줄러\n{"="*60}')

if __name__ == '__main__':
    main()
