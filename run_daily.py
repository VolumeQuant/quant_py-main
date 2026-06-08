"""
로컬 PC 자동 실행 — 매일 포트폴리오 생성 + 텔레그램 전송 + git push

GitHub Actions telegram_daily.yml과 동일한 파이프라인.
Windows Task Scheduler에서 호출.
"""

import subprocess
import sys
import os
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

# ── 경로 설정 ──
SCRIPT_DIR = Path(__file__).parent.resolve()
PYTHON = sys.executable
LOG_DIR = SCRIPT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)


def log(msg: str, f=None):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    if f:
        f.write(line + "\n")
        f.flush()


def run_script(name: str, timeout: int, logfile, extra_env=None):
    """subprocess로 Python 스크립트 실행 (라인 스트리밍 + timeout 보존).

    이전 capture_output 방식은 timeout 시 stdout 버퍼가 손실됨.
    Popen + readline으로 진행 로그를 logfile에 즉시 기록 → timeout 시에도 보존.
    """
    import time as _time
    script = SCRIPT_DIR / name
    log(f"실행: {name}", logfile)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    if extra_env:
        env.update(extra_env)
    proc = subprocess.Popen(
        [PYTHON, "-u", str(script)],
        cwd=str(SCRIPT_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        bufsize=1,
    )
    t_start = _time.time()
    timed_out = False
    try:
        for line in proc.stdout:
            logfile.write(line)
            logfile.flush()
            if _time.time() - t_start > timeout:
                timed_out = True
                break
    finally:
        if timed_out:
            proc.kill()
            try: proc.wait(timeout=5)
            except subprocess.TimeoutExpired: pass
            raise subprocess.TimeoutExpired(name, timeout)
        proc.wait()
    return proc.returncode == 0


def send_error_notification():
    """포트폴리오 생성 실패 시 텔레그램 에러 알림"""
    try:
        import requests
        sys.path.insert(0, str(SCRIPT_DIR))
        from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID
        msg = (
            "<b>[시스템 알림]</b>\n\n"
            "데이터 소스(KRX) 점검 중으로 오늘 리포트를 생성하지 못했습니다.\n"
            "기존 포트폴리오를 유지해 주세요.\n\n"
            "<i>pykrx/KRX API 복구 시 자동 정상화됩니다.</i>"
        )
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_PRIVATE_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
        print("에러 알림 전송 완료")
    except Exception as e:
        print(f"에러 알림 전송 실패: {e}")


def git_push_state(logfile):
    """state/ 디렉토리 git commit + push"""
    repo_root = SCRIPT_DIR  # git 루트 = 스크립트 디렉토리
    today = datetime.now().strftime("%Y%m%d")
    cmds = [
        ["git", "add", "state/"],
        ["git", "diff", "--cached", "--quiet"],
    ]
    # git add
    subprocess.run(cmds[0], cwd=str(repo_root), capture_output=True)
    # 변경 확인
    result = subprocess.run(cmds[1], cwd=str(repo_root), capture_output=True)
    if result.returncode != 0:  # 변경 있음
        subprocess.run(
            ["git", "commit", "-m", f"state: daily ranking {today}"],
            cwd=str(repo_root), capture_output=True,
        )
        push = subprocess.run(
            ["git", "push"],
            cwd=str(repo_root), capture_output=True, text=True, timeout=30,
        )
        log(f"git push: {'성공' if push.returncode == 0 else '실패'}", logfile)
    else:
        log("git: 변경 없음", logfile)


def _git_pull_safe(logfile=None):
    """run_daily 시작 시 origin/main rebase pull (working tree clean 시만, 안전)"""
    try:
        st = subprocess.run(
            ['git', 'status', '--porcelain'],
            cwd=str(SCRIPT_DIR), capture_output=True, text=True, timeout=30,
        )
        if st.stdout.strip():
            if logfile: log("git pull skip: working tree dirty", logfile)
            return False
        result = subprocess.run(
            ['git', 'pull', '--rebase', 'origin', 'main'],
            cwd=str(SCRIPT_DIR), capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            if logfile: log("git pull --rebase: 성공", logfile)
            return True
        else:
            if logfile: log(f"git pull 실패: {(result.stderr or '')[:200]}", logfile)
            return False
    except Exception as e:
        if logfile: log(f"git pull 오류: {e}", logfile)
        return False


def _validate_ranking(base_date, state_dir, threshold=320, logfile=None):
    """ranking 종목 수 검증 — 임계 미달 시 데이터 정합성 의심
    Returns: (ok: bool, n_stocks: int)
    """
    import json
    ranking_path = Path(state_dir) / f'ranking_{base_date}.json'
    if not ranking_path.exists():
        if logfile: log(f"ranking 파일 없음: {ranking_path}", logfile)
        return False, 0
    try:
        with open(ranking_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        n = len(data.get('rankings', []))
        ok = n >= threshold
        if logfile:
            log(f"ranking 검증: {n}종목 (임계 {threshold}) — {'통과' if ok else '⚠️ 미달'}", logfile)
        return ok, n
    except Exception as e:
        if logfile: log(f"ranking 검증 오류: {e}", logfile)
        return False, 0


def _get_collection_count(base_date, logfile=None):
    """오늘 전종목 수집 수 (market_cap → fundamental 폴백). 행수만.
    데이터 사고(pykrx 대량실패 → 급감/누락) vs 시장 breadth 붕괴(수집 정상, 필터만 적음) 구분용.
    정상 ~2700-3000. v80.25(2026-06-08) 도입."""
    import pandas as pd
    cache = SCRIPT_DIR / 'data_cache'
    for prefix in ('market_cap_ALL_', 'fundamental_batch_ALL_'):
        p = cache / f'{prefix}{base_date}.parquet'
        if p.exists():
            try:
                return len(pd.read_parquet(p))
            except Exception as e:
                if logfile: log(f"수집수 읽기 오류({prefix}): {e}", logfile)
    return 0


def _send_personal_warning(msg, logfile=None):
    """개인봇 DM만 발송 (채널 X) — 데이터 정합성 사고 알림용"""
    try:
        import requests
        sys.path.insert(0, str(SCRIPT_DIR))
        from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_PRIVATE_ID, "text": msg, "parse_mode": "HTML"},
            timeout=30,
        )
        if logfile:
            log(f"개인봇 알림: {'성공' if r.ok else f'실패 ({r.status_code})'}", logfile)
        return r.ok
    except Exception as e:
        if logfile: log(f"개인봇 알림 실패: {e}", logfile)
        return False


def _run_fg_single(base_date, env_vars, state_dir, logfile):
    """FG subprocess 1회 실행 → ranking JSON 생성"""
    fg_script = str(SCRIPT_DIR / 'backtest' / 'fast_generate_rankings_v2.py')
    fg_cmd = [PYTHON, '-u', fg_script, base_date, base_date, f'--state-dir={state_dir}']
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PRODUCTION_MODE": "1"}
    env.update(env_vars)
    result = subprocess.run(
        fg_cmd, cwd=str(SCRIPT_DIR), capture_output=True,
        text=True, timeout=600, encoding="utf-8", errors="replace", env=env,
    )
    if result.stdout:
        logfile.write(result.stdout)
    if result.stderr:
        logfile.write(result.stderr)
    logfile.flush()
    return result.returncode == 0


def _build_mode_env(params):
    """regime params → FG env vars dict"""
    env = {
        'FACTOR_V_W': str(params['V_W']),
        'FACTOR_Q_W': str(params['Q_W']),
        'FACTOR_G_W': str(params['G_W']),
        'FACTOR_M_W': str(params['M_W']),
        'G_REVENUE_WEIGHT': str(params['G_REV']),
        'MOM_PERIOD': params['MOM_PERIOD'],
        'G_SUB1': params['G_SUB1'],
        'G_SUB2': params['G_SUB2'],
    }
    # 3팩터 G서브 (v77)
    if params.get('G_SUB3'):
        env['G_SUB3'] = params['G_SUB3']
        env['G_W1'] = str(params['G_W1'])
        env['G_W2'] = str(params['G_W2'])
        env['G_W3'] = str(params['G_W3'])
    # v80.12 (2026-05-18): QoQ 패널티 + SG6 (boost only)
    if params.get('G_QOQ_PENALTY'):
        env['G_QOQ_PENALTY'] = str(params['G_QOQ_PENALTY'])
        env['G_QOQ_PENALTY_THRESHOLD'] = str(params['G_QOQ_PENALTY_THRESHOLD'])
        env['G_QOQ_PENALTY_MULTIPLIER'] = str(params['G_QOQ_PENALTY_MULTIPLIER'])
        env['G_QOQ_SG6_THRESH'] = str(params['G_QOQ_SG6_THRESH'])
    # v80.20 (2026-05-27): mom_10 + vol_low 신팩터 (boost only)
    if params.get('FACTOR_MOM_10_W'):
        env['FACTOR_MOM_10_W'] = str(params['FACTOR_MOM_10_W'])
    if params.get('FACTOR_VOL_LOW_W'):
        env['FACTOR_VOL_LOW_W'] = str(params['FACTOR_VOL_LOW_W'])
    # v80.23 (2026-06-05): 과열 캡 (성장-밸류 괴리, boost only)
    # 가격반응 PER(시총/TTM순이익) 단면 z 중 비싼 쪽만 감점 → 과열 추격매수 회피
    if params.get('FACTOR_OVERHEAT_W'):
        env['FACTOR_OVERHEAT_W'] = str(params['FACTOR_OVERHEAT_W'])
    return env


def _postprocess_ranking(base_date, state_dir, mode, logfile):
    """FG 출력에 weighted_rank + per/pbr/roe + mode 추가"""
    import json
    import pandas as pd

    ranking_path = Path(state_dir) / f'ranking_{base_date}.json'
    if not ranking_path.exists():
        log(f"ranking 파일 없음: {ranking_path}", logfile)
        return False

    with open(ranking_path, 'r', encoding='utf-8') as f:
        ranking_data = json.load(f)
    rankings = ranking_data.get('rankings', [])
    if not rankings:
        return False

    # weighted_rank: 같은 mode의 이전 파일에서 T-1, T-2 로드 (Top 20 한정)
    # CLAUDE.md 의도: 빈 날(Top 20 안 들면) = PENALTY 50. cr 값 그대로 X.
    avail = sorted([fp.stem.replace('ranking_', '') for fp in Path(state_dir).glob('ranking_*.json')
                     if len(fp.stem.replace('ranking_', '')) == 8])
    prev = [d for d in avail if d < base_date]
    PENALTY = 50

    def _load_top20_cr_map(date_str):
        """Top 20 안 종목만 cr 매핑 (Top 20 밖 = PENALTY 적용 대상)"""
        pp = Path(state_dir) / f'ranking_{date_str}.json'
        if not pp.exists():
            return {}
        with open(pp, 'r', encoding='utf-8') as f:
            pd_data = json.load(f)
        return {r['ticker']: r.get('composite_rank', r['rank'])
                for r in pd_data.get('rankings', [])
                if r.get('composite_rank', r.get('rank', 999)) <= 20}

    t1_map = _load_top20_cr_map(prev[-1]) if len(prev) >= 1 else {}
    t2_map = _load_top20_cr_map(prev[-2]) if len(prev) >= 2 else {}

    for item in rankings:
        r0 = item.get('composite_rank', item['rank'])
        r1 = t1_map.get(item['ticker'], PENALTY)
        r2 = t2_map.get(item['ticker'], PENALTY)
        # v80.13 (2026-05-18): wr 가중치 50:30:20 → 40:35:25 (BT Cal 2.22→2.60, WF min 0.14→0.18)
        item['weighted_rank'] = round(r0 * 0.4 + r1 * 0.35 + r2 * 0.25, 1)

    rankings.sort(key=lambda x: x['weighted_rank'])
    for i, item in enumerate(rankings):
        item['rank'] = i + 1

    # per/pbr/roe 보충
    fund_files = sorted((SCRIPT_DIR / 'data_cache').glob('fundamental_batch_ALL_*.parquet'))
    if fund_files:
        try:
            fund_df = pd.read_parquet(fund_files[-1])
            for item in rankings:
                ticker = item['ticker']
                if ticker in fund_df.index:
                    row = fund_df.loc[ticker]
                    for col, key in [('PER', 'per'), ('PBR', 'pbr')]:
                        v = row.get(col)
                        if v is not None and pd.notna(v) and v > 0:
                            item[key] = round(float(v), 2)
                    eps, bps = row.get('EPS'), row.get('BPS')
                    if eps is not None and bps is not None and pd.notna(eps) and pd.notna(bps) and bps > 0 and eps != 0:
                        item['roe'] = round(float(eps / bps * 100), 2)
        except Exception:
            pass

    # mode + 저장
    metadata = ranking_data.get('metadata', {})
    metadata['mode'] = mode
    ranking_data['rankings'] = rankings
    ranking_data['metadata'] = metadata
    with open(ranking_path, 'w', encoding='utf-8') as f:
        json.dump(ranking_data, f, ensure_ascii=False, indent=2)
    return True


def run_fg_pipeline(base_date, regime_env, regime_mode, logfile):
    """FG dual-mode 파이프라인: 매일 boost + defense 양쪽 순위 생성

    1. data_refresher로 캐시 갱신
    2. FG(boost) → state/ranking_{date}.json
    3. FG(defense) → state/ranking_def_{date}.json
    4. 활성 모드 파일에 weighted_rank 후처리
    """
    from regime_indicator import get_regime_params

    # --- Step 1: 데이터 캐시 갱신 ---
    log("데이터 캐시 갱신 (data_refresher)", logfile)
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        from data_refresher import refresh_all
        refresh_all(base_date)
    except Exception as e:
        log(f"데이터 갱신 오류: {e} - 기존 캐시로 진행", logfile)

    state_dir = str(SCRIPT_DIR / 'state')
    state_def_dir = str(SCRIPT_DIR / 'state' / 'defense')
    os.makedirs(state_def_dir, exist_ok=True)

    boost_params = get_regime_params('boost')
    defense_params = get_regime_params('defense')

    # --- Step 2+3: FG(boost) + FG(defense) 병렬 실행 ---
    log("FG 스코어링: boost + defense 병렬", logfile)
    fg_script = str(SCRIPT_DIR / 'backtest' / 'fast_generate_rankings_v2.py')
    base_env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PRODUCTION_MODE": "1"}

    boost_env = {**base_env, **_build_mode_env(boost_params)}
    defense_env = {**base_env, **_build_mode_env(defense_params)}

    boost_cmd = [PYTHON, '-u', fg_script, base_date, base_date, f'--state-dir={state_dir}']
    def_cmd = [PYTHON, '-u', fg_script, base_date, base_date, f'--state-dir={state_def_dir}']

    proc_boost = subprocess.Popen(boost_cmd, cwd=str(SCRIPT_DIR), stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, env=boost_env, text=True, encoding="utf-8", errors="replace")
    proc_def = subprocess.Popen(def_cmd, cwd=str(SCRIPT_DIR), stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, env=defense_env, text=True, encoding="utf-8", errors="replace")

    # 양쪽 완료 대기 (timeout 10분)
    try:
        boost_out, boost_err = proc_boost.communicate(timeout=600)
        if boost_out: logfile.write(boost_out)
        if boost_err: logfile.write(boost_err)
    except subprocess.TimeoutExpired:
        proc_boost.kill()
        boost_out, boost_err = proc_boost.communicate()

    try:
        def_out, def_err = proc_def.communicate(timeout=600)
        if def_out: logfile.write(def_out)
        if def_err: logfile.write(def_err)
    except subprocess.TimeoutExpired:
        proc_def.kill()
        def_out, def_err = proc_def.communicate()

    logfile.flush()
    ok_boost = proc_boost.returncode == 0
    ok_def = proc_def.returncode == 0

    if not ok_boost:
        log("FG boost 실패", logfile)
        return False
    if not ok_def:
        log("FG defense 실패 (비치명적)", logfile)

    # --- Step 4: 활성 모드 파일에 weighted_rank 후처리 ---
    if regime_mode == 'boost':
        active_dir = state_dir
    else:
        # defense가 활성이면 defense 파일을 메인으로 복사
        import shutil
        def_file = Path(state_def_dir) / f'ranking_{base_date}.json'
        main_file = Path(state_dir) / f'ranking_{base_date}.json'
        if def_file.exists():
            shutil.copy2(def_file, main_file)
        active_dir = state_dir

    log(f"가중순위 후처리: {regime_mode}", logfile)
    ok = _postprocess_ranking(base_date, active_dir, regime_mode, logfile)
    if not ok:
        log("후처리 실패", logfile)
        return False

    # defense 파일에도 후처리 (3일 히스토리용)
    if ok_def:
        _postprocess_ranking(base_date, state_def_dir, 'defense', logfile)

    log(f"완료: boost+defense 양쪽 생성, 활성={regime_mode}", logfile)
    return True


def _is_trading_day():
    """오늘이 거래일인지 확인 (삼성전자 OHLCV로 판단)"""
    try:
        from pykrx import stock as _pykrx
        today_str = datetime.now().strftime('%Y%m%d')
        df = _pykrx.get_market_ohlcv(today_str, today_str, '005930')
        return not df.empty
    except Exception:
        # API 실패 시 요일로 판단 (주말 제외)
        return datetime.now().weekday() < 5


def main():
    today = datetime.now().strftime("%Y%m%d")
    log_path = LOG_DIR / f"daily_{today}.log"
    lock_file = LOG_DIR / f"daily_{today}.lock"

    # 주말/공휴일 스킵 (TEST_MODE에서는 무시)
    is_test = os.environ.get('TEST_MODE') == '1'
    if not is_test and not _is_trading_day():
        print(f"[스킵] 오늘({today})은 휴장일입니다.")
        return

    # 중복 실행 방지 (TEST_MODE에서는 스킵)
    if lock_file.exists() and not is_test:
        print(f"[스킵] 오늘({today}) 이미 실행 완료됨 ({lock_file})")
        return

    with open(log_path, "a", encoding="utf-8") as logfile:
        log("=" * 50, logfile)
        log("퀀트 데일리 파이프라인 시작", logfile)
        log("=" * 50, logfile)

        # 0.0. git pull (origin/main 자동 동기화 — 다른 PC에서 push한 코드 변경 자동 반영)
        log("git pull 동기화", logfile)
        _git_pull_safe(logfile)

        # 0. DART 증분 갱신 (매일, 비공시 시즌에는 스크립트 내부에서 즉시 종료)
        # 종목명 캐시 — 별도 스케줄러 (매주 월요일 09시)
        log("DART 캐시 증분 갱신", logfile)
        try:
            ok_dart = run_script("refresh_dart_cache.py", timeout=18000, logfile=logfile)
            log(f"DART 갱신: {'성공' if ok_dart else '실패'}", logfile)
        except subprocess.TimeoutExpired:
            log("DART 갱신 타임아웃 (5시간) — 기존 캐시로 진행", logfile)
        except Exception as e:
            log(f"DART 갱신 오류: {e} — 기존 캐시로 진행", logfile)

        # 0.1. FnGuide 증분 (DART 최근 공시 종목만, rcept_dt 역추적 포함)
        log("FnGuide 증분 갱신 (DART 최근 공시 종목)", logfile)
        try:
            ok_fng = run_script("refresh_fnguide_incremental.py", timeout=18000, logfile=logfile)
            log(f"FnGuide 갱신: {'성공' if ok_fng else '실패(비치명적)'}", logfile)
        except subprocess.TimeoutExpired:
            log("FnGuide 갱신 타임아웃 (5시간) — 기존 캐시로 진행", logfile)
        except Exception as e:
            log(f"FnGuide 갱신 오류: {e} — 기존 캐시로 진행", logfile)

        # 0.2. DART vs FN 캐시 무결성 자동 검사 (2026-05-12 SG&A 사고 후 추가)
        # 5/15 1Q 폭주 대비 강화 (2026-05-12): 의심 시 개인봇 즉시 알림 (비차단 유지)
        log("DART vs FN 캐시 무결성 검사", logfile)
        try:
            ok_health = run_script("monitor_dart_fn_health.py", timeout=300, logfile=logfile)
            if not ok_health:
                log("⚠️ 캐시 무결성 의심 — 개인봇 즉시 알림", logfile)
                _send_personal_warning(
                    "⚠️ <b>캐시 무결성 의심 감지</b>\n\n"
                    "DART vs FN baseline 임계값 초과. monitor_dart_fn_health.py 로그 점검 필요.\n"
                    "5/15 1Q 폭주 시기 — 매핑 사고 재발 가능성 점검 권장.\n\n"
                    "ranking 발송은 계속 진행 (비차단).",
                    logfile=logfile,
                )
        except Exception as e:
            log(f"무결성 검사 오류: {e} — 비차단", logfile)

        # 0.3. OHLCV 신규 종목 증분 수집
        #   시총 1000억+ 인데 OHLCV에 없는 종목 → 개별 수집 (252거래일)
        log("OHLCV 신규 종목 증분 수집 시작", logfile)
        try:
            import pandas as pd
            import numpy as np
            import time as _time

            data_cache = SCRIPT_DIR / "data_cache"

            # 1) 가장 긴 OHLCV 파일 선택 — _full 우선
            ohlcv_files = list(data_cache.glob("all_ohlcv_*.parquet"))
            full_ohlcv = [f for f in ohlcv_files if '_full' in f.stem]
            if full_ohlcv:
                ohlcv_files = full_ohlcv
            if ohlcv_files:
                best_ohlcv = None
                best_span = 0
                for f in ohlcv_files:
                    parts = f.stem.split('_')
                    if len(parts) >= 4:
                        span = int(parts[3]) - int(parts[2])
                        if span > best_span:
                            best_span = span
                            best_ohlcv = f
                if best_ohlcv is None:
                    best_ohlcv = sorted(ohlcv_files)[-1]

                ohlcv_df = pd.read_parquet(best_ohlcv)
                existing_tickers = set(ohlcv_df.columns)
                log(f"  OHLCV 파일: {best_ohlcv.name} ({len(existing_tickers)}종목)", logfile)

                # 2) 최신 market_cap에서 시총 1000억+ 종목
                mc_files = sorted(data_cache.glob("market_cap_ALL_*.parquet"))
                if mc_files:
                    mc_df = pd.read_parquet(mc_files[-1])
                    if '시가총액' in mc_df.columns:
                        large_cap = mc_df[mc_df['시가총액'] >= 100_000_000_000]  # 1000억
                        large_tickers = set(large_cap.index.astype(str))
                        log(f"  시총 1000억+: {len(large_tickers)}종목", logfile)

                        # 3) 누락 종목 찾기
                        missing = large_tickers - existing_tickers
                        if missing:
                            log(f"  신규 종목 발견: {len(missing)}개 → 개별 OHLCV 수집", logfile)

                            # pykrx 임포트 + 인증
                            from pykrx import stock as pykrx_stock
                            import krx_auth
                            krx_auth.login()

                            # 252거래일 ≈ 370일
                            ohlcv_end = ohlcv_df.index[-1].strftime('%Y%m%d')
                            from datetime import timedelta as _td
                            ohlcv_start = (ohlcv_df.index[-1] - _td(days=370)).strftime('%Y%m%d')

                            collected = 0
                            failed = 0
                            for ticker in sorted(missing):
                                try:
                                    tk_df = pykrx_stock.get_market_ohlcv_by_date(
                                        ohlcv_start, ohlcv_end, ticker
                                    )
                                    if not tk_df.empty and '종가' in tk_df.columns:
                                        ohlcv_df[ticker] = tk_df['종가'].reindex(ohlcv_df.index)
                                        collected += 1
                                    _time.sleep(1)  # CRITICAL: 1초 sleep, IP 차단 방지
                                except Exception as e:
                                    failed += 1
                                    log(f"    {ticker} 수집 실패: {e}", logfile)
                                    _time.sleep(1)

                            if collected > 0:
                                # 기존 파일에 덮어쓰기 (파일명 유지)
                                ohlcv_df.to_parquet(best_ohlcv)
                                log(f"  OHLCV 증분 완료: +{collected}종목 (실패 {failed}) → {best_ohlcv.name}", logfile)

                                # 다른 OHLCV 파일에도 신규 종목 추가
                                for other_f in data_cache.glob("all_ohlcv_*.parquet"):
                                    if other_f == best_ohlcv:
                                        continue
                                    try:
                                        other_df = pd.read_parquet(other_f)
                                        new_cols = set(ohlcv_df.columns) - set(other_df.columns)
                                        if new_cols:
                                            for col in new_cols:
                                                other_df[col] = ohlcv_df[col].reindex(other_df.index)
                                            other_df.to_parquet(other_f)
                                            log(f"    동기화: {other_f.name} (+{len(new_cols)}종목)", logfile)
                                    except Exception:
                                        pass
                            else:
                                log(f"  수집된 종목 없음 (실패 {failed})", logfile)
                        else:
                            log("  누락 종목 없음 — 스킵", logfile)
                    else:
                        log("  market_cap에 시가총액 컬럼 없음 — 스킵", logfile)
                else:
                    log("  market_cap 파일 없음 — 스킵", logfile)
            else:
                log("  OHLCV 파일 없음 — 스킵", logfile)
        except Exception as e:
            log(f"OHLCV 증분 수집 오류: {e} — 기존 데이터로 진행", logfile)

        # 0.5. 국면 판단 (v80.18: KP_MA_CROSS — MA20 > MA80, 5일 confirm)
        try:
            sys.path.insert(0, str(SCRIPT_DIR))
            from regime_indicator import get_current_regime, get_regime_params, MA_PERIOD, CONFIRM_DAYS, SHORT_MA, LONG_MA
            log(f"국면 판단 (KP_MA_CROSS: MA{SHORT_MA} > MA{LONG_MA}, {CONFIRM_DAYS}d 확인)", logfile)
            import pandas as pd
            from pathlib import Path

            # KOSPI MA 계산 (v80.18: MA cross)
            kospi_close = kospi_ma = kospi_ma200 = kospi_short_ma = kospi_long_ma = kospi_ret20 = None
            kospi_file = SCRIPT_DIR / 'data_cache' / 'kospi_yf.parquet'
            if kospi_file.exists():
                _df = pd.read_parquet(kospi_file)
                kp = _df.iloc[:, 0].copy()
                for _c in _df.columns[1:]:  # 옛 멀티컬럼 호환
                    kp = kp.fillna(_df[_c])
                kp = kp.dropna()
                if len(kp) >= max(LONG_MA, MA_PERIOD, 200):
                    kospi_close = float(kp.iloc[-1])
                    kospi_ma = float(kp.rolling(MA_PERIOD).mean().iloc[-1])  # 호환
                    kospi_ma200 = float(kp.rolling(200).mean().iloc[-1])  # 호환
                    kospi_short_ma = float(kp.rolling(SHORT_MA).mean().iloc[-1])  # 신규 v80.18
                    kospi_long_ma = float(kp.rolling(LONG_MA).mean().iloc[-1])  # 신규 v80.18
                if len(kp) >= 21:
                    kospi_ret20 = float(kp.iloc[-1] / kp.iloc[-21] - 1)
                log(f"KOSPI 로드: close={kospi_close} MA{SHORT_MA}={kospi_short_ma} MA{LONG_MA}={kospi_long_ma}", logfile)
            else:
                log(f"KOSPI 파일 없음: {kospi_file}", logfile)

            regime = get_current_regime(
                kospi_close=kospi_close, kospi_ma=kospi_ma,
                kospi_ma200=kospi_ma200,
                kospi_short_ma=kospi_short_ma, kospi_long_ma=kospi_long_ma,
                kospi_ret20=kospi_ret20,
                date_str=today
            )
            # FG 파이프라인은 underlying_mode(boost/defense)로 ranking 생성
            # cash 모드에서도 defense ranking을 만들어 두되, 매수 스킵은 send_telegram에서 처리
            _underlying = regime.get('underlying_mode', regime['mode'])
            params = get_regime_params(_underlying)
            # 표시용 라벨은 최종 모드(cash 포함)
            display_params = get_regime_params(regime['mode'])
            kp_str = f'KOSPI={kospi_close:.0f} MA{SHORT_MA}={kospi_short_ma:.0f} MA{LONG_MA}={kospi_long_ma:.0f}' if kospi_short_ma else '?'
            ret_str = f' ret20={kospi_ret20*100:+.1f}%' if kospi_ret20 is not None else ''
            log(f"국면: {display_params['icon']} {display_params['label']} ({kp_str}{ret_str}, 신호={regime['signal']}, 전환={regime['switched']})", logfile)
        except Exception as e:
            log(f"국면 판단 실패: {e} — 기본 방어 모드", logfile)
            from regime_indicator import get_regime_params
            regime = {'mode': 'defense', 'underlying_mode': 'defense', 'switched': False,
                      'signal': 'defense', 'streak': 0, 'prev_mode': 'defense'}
            params = get_regime_params('defense')
            display_params = params

        # 1. 포트폴리오 생성 (국면 파라미터 환경변수 주입)
        # v77.1: cash 모드에서도 defense ranking 생성 (매수 스킵은 send_telegram에서)
        regime_env = {
            'FACTOR_V_W': str(params['V_W']),
            'FACTOR_Q_W': str(params['Q_W']),
            'FACTOR_G_W': str(params['G_W']),
            'FACTOR_M_W': str(params['M_W']),
            'G_REVENUE_WEIGHT': str(params['G_REV']),
            'USE_REV_ACCEL': '1' if params['USE_REV_ACCEL'] else '0',
            'REGIME_MODE': regime['mode'],  # boost/defense/cash (최종)
            'REGIME_UNDERLYING_MODE': regime.get('underlying_mode', regime['mode']),
            'REGIME_ENTRY_RANK': str(params['ENTRY_RANK']),
            'REGIME_EXIT_RANK': str(params['EXIT_RANK']),
            'REGIME_MAX_SLOTS': str(params['MAX_SLOTS']),
            'MOM_PERIOD': params['MOM_PERIOD'],
            'G_SUB1': params['G_SUB1'] or '',
            'G_SUB2': params['G_SUB2'] or '',
            'G_SUB3': params['G_SUB3'] or '',
            'G_W1': str(params['G_W1']) if params['G_W1'] is not None else '',
            'G_W2': str(params['G_W2']) if params['G_W2'] is not None else '',
            'G_W3': str(params['G_W3']) if params['G_W3'] is not None else '',
            'REGIME_SWITCHED': '1' if regime.get('switched') else '0',
            'REGIME_PREV_MODE': regime.get('prev_mode', ''),
        }
        # v80.12: QoQ 패널티 (boost only)
        if params.get('G_QOQ_PENALTY'):
            regime_env['G_QOQ_PENALTY'] = str(params['G_QOQ_PENALTY'])
            regime_env['G_QOQ_PENALTY_THRESHOLD'] = str(params['G_QOQ_PENALTY_THRESHOLD'])
            regime_env['G_QOQ_PENALTY_MULTIPLIER'] = str(params['G_QOQ_PENALTY_MULTIPLIER'])
            regime_env['G_QOQ_SG6_THRESH'] = str(params['G_QOQ_SG6_THRESH'])

        use_new = os.environ.get('USE_NEW_PIPELINE', '1') == '1'

        if use_new:
            # === 새 파이프라인: data_refresher + FG 직접 + weighted_rank ===
            log("파이프라인: FG 직접 호출 (v75)", logfile)
            try:
                ok = run_fg_pipeline(today, regime_env, regime['mode'], logfile)
            except subprocess.TimeoutExpired:
                log("FG 파이프라인 타임아웃 (10분)", logfile)
                ok = False
            except Exception as e:
                log(f"FG 파이프라인 오류: {e}", logfile)
                ok = False
        else:
            # === 기존 파이프라인: CP 경유 (레거시) ===
            log("파이프라인: CP 경유 (레거시)", logfile)
            try:
                ok = run_script("create_current_portfolio.py", timeout=1200, logfile=logfile, extra_env=regime_env)
            except subprocess.TimeoutExpired:
                log("포트폴리오 생성 타임아웃 (20분)", logfile)
                ok = False
            except Exception as e:
                log(f"포트폴리오 생성 오류: {e}", logfile)
                ok = False

        if not ok:
            log("포트폴리오 실패 -> 에러 알림 전송", logfile)
            send_error_notification()
            return

        # 1.5. ranking 검증 — 데이터 정합성 미달 시 30분 후 재시도 (B 안전망)
        # 매핑 버그 같은 외부 트리거 사고 방지 (2026-05-04 도입)
        state_dir = SCRIPT_DIR / 'state'
        ok_val, n_stocks = _validate_ranking(today, state_dir, threshold=150, logfile=logfile)
        if not ok_val:
            # v80.25 (2026-06-08): 수집 vs 필터 구분.
            #   수집 정상(1500+)인데 필터 통과만 적음 = 시장 breadth 붕괴(폭락 등) → 발송 (데이터 사고 아님)
            #   수집 자체도 적음 = wholesale 데이터 사고 → 차단 + 30분 후 재시도
            coll_n = _get_collection_count(today, logfile)
            COLL_MIN = 1500
            if coll_n >= COLL_MIN:
                log(f"ℹ️ ranking {n_stocks}종목<150 이나 수집 {coll_n}종목 정상 → 시장 breadth(폭락) 판단, 정상 발송", logfile)
                _send_personal_warning(
                    f"ℹ️ <b>유니버스 축소 — 시장 breadth</b>\n\n"
                    f"필터 통과: <b>{n_stocks}</b>종목 (임계 150 미달)\n"
                    f"전종목 수집: <b>{coll_n}</b>종목 (정상)\n\n"
                    f"수집 정상 → 데이터 사고 아님. 폭락 등으로 120일선 위 종목이 적은 것 → <b>정상 발송 진행.</b>",
                    logfile=logfile,
                )
                # ok_val 미달이어도 발송 로직으로 자연 진행 (차단·재시도 안 함)
            else:
                log(f"⚠️ ranking {n_stocks}종목 + 수집 {coll_n}종목 둘 다 미달 — 데이터 사고 의심, 채널 차단·재시도", logfile)
                _send_personal_warning(
                    f"⚠️ <b>데이터 사고 의심 — 채널 차단</b>\n\n"
                    f"필터 통과: {n_stocks}종목 / 전종목 수집: <b>{coll_n}</b>종목 (임계 {COLL_MIN} 미달)\n\n"
                    f"수집 자체가 적음 = wholesale 사고 가능성. 채널 발송 보류, 30분 후 재시도.",
                    logfile=logfile,
                )
                import time
                time.sleep(1800)  # 30분
                log("재시도: ranking 재생성", logfile)
                try:
                    ok_retry = run_fg_pipeline(today, regime_env, regime['mode'], logfile)
                except Exception as e:
                    log(f"재시도 ranking 재생성 오류: {e}", logfile)
                    ok_retry = False
                if not ok_retry:
                    _send_personal_warning(
                        f"❌ <b>재시도 ranking 재생성 실패</b>\n\n오늘 채널 발송 보류. 수동 점검 필요.",
                        logfile=logfile,
                    )
                    return
                ok_val, n_stocks = _validate_ranking(today, state_dir, threshold=150, logfile=logfile)
                coll_n = _get_collection_count(today, logfile)
                if coll_n < COLL_MIN:
                    log(f"⚠️ 재시도 후에도 수집 {coll_n}종목 미달 — 데이터 사고 지속, 발송 보류", logfile)
                    _send_personal_warning(
                        f"❌ <b>재시도 후에도 수집 미달({coll_n}종목)</b>\n\n"
                        f"wholesale 사고 지속 의심. 오늘 채널 발송 보류, 수동 점검 필요.",
                        logfile=logfile,
                    )
                    return
                log(f"✅ 재시도: 수집 {coll_n}종목 정상화 (필터 {n_stocks}종목) → 정상 발송 진행", logfile)

        # 2. 텔레그램 전송
        # v77.1: 타임아웃 3분→10분 확장 + Popen 실시간 스트리밍 (멈춘 지점 추적)
        try:
            _script = SCRIPT_DIR / "send_telegram_auto.py"
            log(f"실행: send_telegram_auto.py (타임아웃 600초, 실시간 로깅)", logfile)
            _env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
            if regime_env:
                _env.update(regime_env)
            _proc = subprocess.Popen(
                [PYTHON, str(_script)],
                cwd=str(SCRIPT_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=_env,
                bufsize=1,
            )
            try:
                for _line in _proc.stdout:
                    logfile.write(_line)
                    logfile.flush()
                _proc.wait(timeout=600)
                ok2 = _proc.returncode == 0
                log(f"텔레그램 전송: {'성공' if ok2 else f'실패 (rc={_proc.returncode})'}", logfile)
            except subprocess.TimeoutExpired:
                _proc.kill()
                log("텔레그램 전송 타임아웃 (10분) — 프로세스 강제 종료", logfile)
        except Exception as e:
            log(f"텔레그램 전송 오류: {e}", logfile)

        # 3. git push
        try:
            git_push_state(logfile)
        except Exception as e:
            log(f"git push 오류: {e}", logfile)

        # 완료 lock 생성 (TEST_MODE에서는 생성 안 함)
        if not is_test:
            lock_file.write_text(datetime.now().isoformat(), encoding="utf-8")
        log("파이프라인 완료", logfile)


if __name__ == "__main__":
    main()
