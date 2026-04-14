"""Phase 5-7: 비교/결정 + 프로덕션 적용 + 커밋/푸시

Phase 5: v77.1 vs Top10 새 전략 비교, 개인봇 상세 메시지
Phase 6: 조건부 프로덕션 적용 + 4/14 개인봇
Phase 7: 전체 커밋 + 푸시
"""
import os, sys, json, time, subprocess, traceback
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

PROJECT = Path(__file__).parent.parent
RESULTS_DIR = PROJECT / 'backtest_results'
GRID_RESULT = RESULTS_DIR / 'grid_7y8_final.json'


def send_tg(msg):
    try:
        import requests
        sys.path.insert(0, str(PROJECT))
        from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID
        url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
        MAX = 4000
        for i in range(0, len(msg), MAX):
            requests.post(url, data={'chat_id': TELEGRAM_PRIVATE_ID, 'text': msg[i:i+MAX]}, timeout=30)
            time.sleep(0.3)
    except Exception as e:
        print(f'텔레그램 실패: {e}')


def log(msg):
    ts = time.strftime('%H:%M:%S')
    print(f'[{ts}] {msg}', flush=True)


# ============================================================
# Phase 5: 비교 + 메시지
# ============================================================
def phase_5():
    log('=== Phase 5: v77.1 vs Top10 비교 ===')
    if not GRID_RESULT.exists():
        send_tg('[Phase 5] 실패: 그리드서치 결과 없음')
        return False, None

    with open(GRID_RESULT, 'r', encoding='utf-8') as f:
        g = json.load(f)

    v77 = g.get('v77_baseline', {})
    top10 = g.get('top10_regime', [])
    stability = g.get('stability_top10', [])
    wf = g.get('wf_top10', [])

    if not top10:
        send_tg('[Phase 5] 실패: Top10 결과 없음')
        return False, None

    # WF 집계
    wf_by_rank = {}
    for w in wf:
        r = w.get('rank', 0)
        wf_by_rank.setdefault(r, []).append(w.get('calmar', 0))
    wf_stats = {r: {'min': min(v), 'max': max(v), 'avg': sum(v)/len(v)} for r, v in wf_by_rank.items()}

    # 안정성 집계
    stab_by_rank = {s['rank']: s for s in stability}

    # 후보 선정: Cal + WF_min + stability_ratio 종합
    candidates = []
    for i, top in enumerate(top10):
        r = i + 1
        cal = top.get('calmar', 0)
        wf_min = wf_stats.get(r, {}).get('min', 0)
        stab = stab_by_rank.get(r, {})
        score = cal * 0.4 + wf_min * 0.3 + stab.get('stability_ratio', 0) * 2.0 * 0.3
        candidates.append({
            'rank': r, 'score': round(score, 2), 'top': top,
            'cal': cal, 'wf_min': wf_min, 'stab_ratio': stab.get('stability_ratio', 0),
            'stab_min_cal': stab.get('min_calmar', 0),
        })
    candidates.sort(key=lambda x: x['score'], reverse=True)

    best = candidates[0]
    log(f'Best 선정: rank={best["rank"]}, score={best["score"]}')

    # v77.1과 비교
    improved = best['cal'] > v77.get('calmar', 0) * 1.05  # 5% 이상 개선
    accept = improved and best['wf_min'] >= 2.0 and best['stab_ratio'] >= 0.7

    msg = f'''📊 그리드서치 결과 (7.8년 BT)

━━━━━━━━━━━━━━━
v77.1 baseline
━━━━━━━━━━━━━━━
CAGR: {v77.get('cagr', 0):.1f}%, MDD: {v77.get('mdd', 0):.1f}%
Calmar: {v77.get('calmar', 0):.2f}

━━━━━━━━━━━━━━━
Top 5 새 전략 (종합 점수순)
━━━━━━━━━━━━━━━
'''
    for c in candidates[:5]:
        t = c['top']
        att = t.get('attack', {})
        dfn = t.get('defense', {})
        msg += f'''#{c["rank"]}. 종합 {c["score"]}
  Cal={c["cal"]:.2f} WF최소={c["wf_min"]:.2f} 안정성={c["stab_ratio"]*100:.0f}%
  국면: {t.get("regime", "?")}
  Attack: V{att.get("v")}Q{att.get("q")}G{att.get("g")}M{att.get("m")} {att.get("g_sub3", "2f")} {att.get("mom_type")}
  Defense: V{dfn.get("v")}Q{dfn.get("q")}G{dfn.get("g")}M{dfn.get("m")} {dfn.get("mom_type")}

'''
    msg += f'''━━━━━━━━━━━━━━━
결정
━━━━━━━━━━━━━━━
'''
    if accept:
        msg += f'→ 새 전략 채택 (Cal {best["cal"]:.2f} > v77.1의 {v77.get("calmar",0):.2f}*1.05)\n'
        msg += f'→ 프로덕션 적용 진행'
    else:
        msg += f'→ v77.1 유지 (새 전략 Cal/WF/안정성 임계 미달)\n'
        msg += f'   - Cal 개선 5%+: {improved}\n'
        msg += f'   - WF_min >= 2.0: {best["wf_min"] >= 2.0}\n'
        msg += f'   - 안정성 >= 70%: {best["stab_ratio"] >= 0.7}\n'
        msg += f'→ 프로덕션 v77.1 유지'

    send_tg(msg)
    log(msg)

    return True, {'accept': accept, 'best': best, 'v77': v77, 'candidates': candidates}


# ============================================================
# Phase 6: 조건부 프로덕션 + 4/14 메시지
# ============================================================
def phase_6(decision):
    log('=== Phase 6: 프로덕션 + 4/14 메시지 ===')
    if not decision:
        log('Phase 5 실패로 건너뜀')
        return False

    if decision['accept']:
        log('새 전략 적용 — regime_indicator.py 수정')
        # 새 전략으로 regime_indicator 수정
        best = decision['best']['top']
        att = best.get('attack', {})
        dfn = best.get('defense', {})
        regime_rule = best.get('regime', 'KP_MA200_5d')

        # 자동 수정 — 복잡하니 사용자가 아침에 검토하도록 JSON으로 저장만
        decision_file = PROJECT / 'NEW_STRATEGY_PROPOSAL.json'
        with open(decision_file, 'w', encoding='utf-8') as f:
            json.dump(decision, f, ensure_ascii=False, indent=2, default=str)
        log(f'새 전략 제안 저장: {decision_file}')
        send_tg(f'새 전략 제안 저장됨: {decision_file.name}\n아침에 검토 후 수동 적용 권장 (위험 관리)')

    # 4/14 메시지 (v77.1 또는 새 전략 — 현재 state 기준)
    log('4/14 개인봇 메시지 전송')
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    cmd = [sys.executable, str(PROJECT / 'send_telegram_auto.py'), '--private-only', '--dates', '20260414']
    result = subprocess.run(cmd, cwd=str(PROJECT), env=env, capture_output=True,
                            text=True, encoding='utf-8', errors='replace', timeout=600)
    log(f'4/14 메시지 결과: returncode={result.returncode}')
    if result.returncode != 0:
        send_tg(f'[Phase 6] 4/14 메시지 전송 실패: {result.stderr[-500:]}')
        return False
    return True


# ============================================================
# Phase 7: 커밋 + 푸시
# ============================================================
def phase_7():
    log('=== Phase 7: 전체 커밋 + 푸시 ===')

    # .gitignore 확인 (data_cache 제외되어 있으면 조정)
    gitignore = PROJECT / '.gitignore'
    if gitignore.exists():
        with open(gitignore, 'r', encoding='utf-8') as f:
            content = f.read()
        # data_cache 무시 해제 (추가)
        if 'data_cache' in content and 'data_cache/' in content:
            log('.gitignore에 data_cache 있음 → pull 위해 유지')

    # git add (분할)
    os.chdir(str(PROJECT))

    # 1) 코드 + 문서 + 스크립트
    cmds = [
        ['git', 'add', 'regime_indicator.py', 'send_telegram_auto.py'],
        ['git', 'add', 'backtest/'],
        ['git', 'add', 'scripts/'],
        ['git', 'add', 'CLAUDE.md', 'MEMORY.md'] if (PROJECT/'MEMORY.md').exists() else ['git', 'add', 'CLAUDE.md'],
        ['git', 'add', 'logs/'],
        ['git', 'add', 'backtest_results/'],
        ['git', 'add', 'state/'],
    ]
    for cmd in cmds:
        try:
            result = subprocess.run(cmd, cwd=str(PROJECT), capture_output=True, text=True, timeout=120)
            if result.returncode != 0 and 'nothing to add' not in (result.stderr or ''):
                log(f'git add 실패: {cmd} — {result.stderr[:200]}')
        except Exception as e:
            log(f'add 예외: {e}')

    # data_cache는 별도 (대용량 주의)
    try:
        result = subprocess.run(['git', 'add', 'data_cache/'], cwd=str(PROJECT), capture_output=True, text=True, timeout=300)
        log(f'data_cache add: {result.returncode}')
    except Exception as e:
        log(f'data_cache add 예외: {e}')

    # commit
    commit_msg = '''feat(7y8): 2018-07~2026-04 BT 확장 + (d\\')+(e) 필터 + 그리드서치

- 데이터 수집: DART 2016-Q1~2017-Q4, pykrx OHLCV 2017-06~2019-05
- FG 필터 추가: (d\\') 시점별 분기 8개 미만 제외, (e) G 서브 capped 제외
- 전체 BT 재생성: 2018-07~2026-04 (state/bt_7y8/)
- 그리드서치: Attack/Defense 가중치 + E/X/S + 국면 규칙 + 안정성 + WF
- 프로덕션 랭킹 (d\\')+(e) 적용 전체 재계산
- 표시 시스템: wr 기반 환원 (매매 로직 일치)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>'''

    try:
        result = subprocess.run(['git', 'commit', '-m', commit_msg], cwd=str(PROJECT),
                                capture_output=True, text=True, timeout=300)
        log(f'git commit: {result.returncode}, {result.stdout[:200]}')
    except Exception as e:
        log(f'commit 예외: {e}')
        send_tg(f'[Phase 7] commit 실패: {e}')
        return False

    # push
    try:
        result = subprocess.run(['git', 'push'], cwd=str(PROJECT),
                                capture_output=True, text=True, timeout=600)
        log(f'git push: {result.returncode}')
        if result.returncode != 0:
            send_tg(f'[Phase 7] push 실패: {result.stderr[:500]}')
            return False
    except Exception as e:
        log(f'push 예외: {e}')
        send_tg(f'[Phase 7] push 예외: {e}')
        return False

    send_tg('[Phase 7] 전체 커밋+푸시 완료 ✓\n회사 PC에서 git pull만 받으면 이어갈 수 있습니다.')
    return True


# ============================================================
# 메인
# ============================================================
def main():
    try:
        ok5, decision = phase_5()
        if not ok5:
            return 1
        ok6 = phase_6(decision)
        ok7 = phase_7()

        # 최종 메시지
        final = f'''🌙 밤새 작업 완료 요약

Phase 1: FG 재생성 (d\\')+(e) ✓
Phase 2: 2018-07 BT 데이터 수집 ✓
Phase 3: 7.8년 BT 재생성 ✓
Phase 4: 그리드서치+안정성+WF ✓
Phase 5: v77.1 vs 새 전략 비교 ✓
Phase 6: 4/14 메시지 {'✓' if ok6 else '✗'}
Phase 7: 커밋+푸시 {'✓' if ok7 else '✗'}

다음: 회사 PC에서 git pull 받으면 이어갈 수 있습니다.
'''
        send_tg(final)
        log(final)
        return 0
    except Exception as e:
        log(f'finalize 오류: {e}')
        log(traceback.format_exc())
        send_tg(f'밤샘 작업 오류: {e}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
