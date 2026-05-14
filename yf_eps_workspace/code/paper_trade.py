"""Paper Trade — v80.6 + yf NTM 신호 매핑, 패턴 A/B/C 추출

매일 실행:
  1. v80.6 production ranking (read-only) 로드
  2. yf daily_probe (workspace) 로드
  3. ticker 매핑 + NTM_score 계산
  4. 패턴 A/B/C 분류:
     A — 진입 이중 검증: v80.6 entry 후보(top 2) × yf NTM 강세/약세
     B — 조기 매도: v80.6 보유 후보(top 4 defense / top 5 boost) × yf NTM 큰 하향
     C — Watchlist 격상: v80.6 rank 3~10 × yf NTM 강한 상승
  5. 결과 paper_trade.db 누적 저장

production 무변경. 매매 안 함 (paper trade only).
"""
import sys, json, time, sqlite3
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd
import numpy as np
import glob
from datetime import datetime
from pathlib import Path

WS = Path(r'C:/dev/yf_eps_workspace')
PROD_STATE = Path(r'C:/dev/state')  # read-only
PROD_DEFENSE = Path(r'C:/dev/state/defense')
YF_CACHE = WS / 'data_cache_yf'
DB_PATH = WS / 'paper_trade.db'


# v80.10b 가중치 (US 시스템과 동일)
NTM_WEIGHTS = {'7d': 0.30, '30d': 0.10, '60d': 0.10, '90d': 0.50}

# 패턴 임계
NTM_STRONG_UP = 0.20      # NTM_score > 0.20 = 강한 상승
NTM_STRONG_DOWN = -0.10   # NTM_score < -0.10 = 강한 하락

# v80.6 production 임계
BOOST_ENTRY = 2
BOOST_WATCHLIST = 10
BOOST_SLOTS = 5
DEFENSE_ENTRY = 3
DEFENSE_WATCHLIST = 10
DEFENSE_SLOTS = 4


def init_db():
    """paper_trade.db 초기화"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS signals (
        date TEXT, ticker TEXT, name TEXT,
        mode TEXT,           -- 'boost' or 'defense' (v80.6 regime)
        v80_rank INTEGER, v80_score REAL,
        ntm_score REAL, rev_net30 INTEGER, na INTEGER,
        yf_available INTEGER,
        pattern_A_signal TEXT,   -- 'enter', 'hold_back', 'no_yf', null
        pattern_B_signal TEXT,   -- 'exit_early', 'hold', 'no_yf', null
        pattern_C_signal TEXT,   -- 'promote', 'no_yf', null
        PRIMARY KEY (date, ticker)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS daily_summary (
        date TEXT PRIMARY KEY,
        regime TEXT,
        n_v80_entry INTEGER, n_v80_watchlist INTEGER,
        n_yf_available INTEGER,
        n_pattern_A_hold_back INTEGER,
        n_pattern_B_exit_early INTEGER,
        n_pattern_C_promote INTEGER,
        notes TEXT
    )''')
    conn.commit()
    return conn


def get_latest_ranking(state_dir, date_str=None):
    """state_dir에서 최신 또는 지정 date의 ranking JSON 로드"""
    files = sorted(state_dir.glob('ranking_*.json'))
    if not files:
        return None, None
    if date_str:
        target = state_dir / f'ranking_{date_str}.json'
        if target.exists():
            with open(target, encoding='utf-8') as f:
                return date_str, json.load(f)
    # 최신
    latest = files[-1]
    date_str = latest.stem.replace('ranking_', '')
    with open(latest, encoding='utf-8') as f:
        return date_str, json.load(f)


def get_latest_yf(date_str=None):
    """yf cache 최신 또는 지정 date의 parquet 로드"""
    files = sorted(YF_CACHE.glob('kr_yf_*.parquet'))
    if not files:
        return None, None
    if date_str:
        target = YF_CACHE / f'kr_yf_{date_str}.parquet'
        if target.exists():
            return date_str, pd.read_parquet(target)
    latest = files[-1]
    date_str = latest.stem.replace('kr_yf_', '')
    return date_str, pd.read_parquet(latest)


def compute_ntm_score(row):
    """5스냅샷 변화율 + v80.10b 가중치 (US 패턴)"""
    cur = row.get('0y_current')
    if pd.isna(cur) or cur == 0:
        return np.nan
    score = 0.0
    valid_weight = 0.0
    for k, w in NTM_WEIGHTS.items():
        prev = row.get(f'0y_{k}')
        if pd.isna(prev) or prev == 0:
            continue
        change = (cur - prev) / abs(prev)
        score += w * change
        valid_weight += w
    if valid_weight < 0.5:  # 5스냅샷 중 최소 절반은 유효해야
        return np.nan
    return score / valid_weight  # 정규화


def detect_regime(boost_data, defense_data):
    """국면 추정: 두 ranking 다 있을 때 KOSPI MA250 8d 기반"""
    # 간단히: production은 매일 boost+defense 둘 다 생성. 어느 게 발송됐는지는 regime_state.json
    rs_file = Path(r'C:/dev/state/regime_state.json')
    if rs_file.exists():
        with open(rs_file, encoding='utf-8') as f:
            rs = json.load(f)
        return rs.get('regime', 'unknown')  # 'boost' or 'defense'
    return 'unknown'


def analyze_day(date_str_v80, date_str_yf):
    """단일 날짜 paper trade 분석"""
    print(f'=== paper trade 분석 ===')
    print(f'  v80.6 ranking date: {date_str_v80}')
    print(f'  yf data date: {date_str_yf}')

    # v80.6 ranking 로드 (boost + defense)
    bd, boost_data = get_latest_ranking(PROD_STATE, date_str_v80)
    dd, defense_data = get_latest_ranking(PROD_DEFENSE, date_str_v80)
    if not boost_data or not defense_data:
        print('  ERROR: v80.6 ranking 없음')
        return None

    regime = detect_regime(boost_data, defense_data)
    print(f'  regime: {regime}')

    # 사용할 ranking (regime별)
    use_data = boost_data if regime != 'defense' else defense_data
    entry_rank = BOOST_ENTRY if regime != 'defense' else DEFENSE_ENTRY
    watchlist_rank = BOOST_WATCHLIST  # 동일
    slots = BOOST_SLOTS if regime != 'defense' else DEFENSE_SLOTS

    v80_rankings = use_data['rankings']
    v80_by_tic = {r['ticker']: r for r in v80_rankings}

    # yf 데이터
    yf_df = get_latest_yf(date_str_yf)[1]
    if yf_df is None or len(yf_df) == 0:
        print('  WARN: yf data 없음 — patterns 산출 불가, signals 빈 row만 기록')
        return None
    yf_df['ticker'] = yf_df['ticker'].astype(str).str.zfill(6)
    yf_df['ntm_score'] = yf_df.apply(compute_ntm_score, axis=1)
    yf_by_tic = {row['ticker']: row for _, row in yf_df.iterrows()}

    # 매핑 + 패턴 산출
    signals = []
    pattern_counts = {'A_hold_back': 0, 'B_exit_early': 0, 'C_promote': 0,
                      'A_enter': 0, 'B_hold': 0, 'no_yf': 0}

    for r in v80_rankings:
        tic = r['ticker']
        v_rank = r.get('rank', r.get('composite_rank', 9999))
        v_score = r.get('score', r.get('composite_score', 0))

        yf_row = yf_by_tic.get(tic)
        yf_avail = yf_row is not None and yf_row.get('fy_complete_0y', False)
        ntm = yf_row['ntm_score'] if yf_row is not None else np.nan
        rev_net = (yf_row.get('up30', 0) - yf_row.get('dn30', 0)) if yf_row is not None else None
        na = yf_row.get('na') if yf_row is not None else None

        # 패턴 A: 진입 이중 검증
        pa = None
        if v_rank <= entry_rank:
            if not yf_avail:
                pa = 'no_yf'
                pattern_counts['no_yf'] += 1
            elif pd.notna(ntm) and ntm > 0:
                pa = 'enter'   # v80.6 + yf 강세 = 동일
                pattern_counts['A_enter'] += 1
            else:
                pa = 'hold_back'   # v80.6 강세 + yf 약세/없음 = 보류
                pattern_counts['A_hold_back'] += 1

        # 패턴 B: 조기 매도 (slots 안 종목 = 보유 가정)
        pb = None
        if v_rank <= slots:
            if not yf_avail:
                pb = 'no_yf'
            elif pd.notna(ntm) and ntm < NTM_STRONG_DOWN:
                pb = 'exit_early'   # v80.6 보유 + yf 큰 하향 = 조기 매도 신호
                pattern_counts['B_exit_early'] += 1
            else:
                pb = 'hold'
                pattern_counts['B_hold'] += 1

        # 패턴 C: Watchlist 격상
        pc = None
        if (entry_rank < v_rank <= watchlist_rank):
            if not yf_avail:
                pc = 'no_yf'
            elif pd.notna(ntm) and ntm > NTM_STRONG_UP:
                pc = 'promote'   # v80.6 watchlist + yf 큰 상승 = 격상 후보
                pattern_counts['C_promote'] += 1

        signals.append({
            'date': date_str_v80, 'ticker': tic, 'name': r.get('name', ''),
            'mode': regime, 'v80_rank': v_rank, 'v80_score': v_score,
            'ntm_score': float(ntm) if pd.notna(ntm) else None,
            'rev_net30': int(rev_net) if rev_net is not None and pd.notna(rev_net) else None,
            'na': int(na) if na is not None and pd.notna(na) else None,
            'yf_available': 1 if yf_avail else 0,
            'pattern_A_signal': pa, 'pattern_B_signal': pb, 'pattern_C_signal': pc,
        })

    return signals, pattern_counts, regime


def save_signals(conn, signals, regime):
    if not signals:
        return
    c = conn.cursor()
    for s in signals:
        c.execute('''INSERT OR REPLACE INTO signals VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (s['date'], s['ticker'], s['name'], s['mode'],
             s['v80_rank'], s['v80_score'],
             s['ntm_score'], s['rev_net30'], s['na'], s['yf_available'],
             s['pattern_A_signal'], s['pattern_B_signal'], s['pattern_C_signal']))
    conn.commit()


def save_summary(conn, date_str, regime, signals, counts):
    n_v80_entry = sum(1 for s in signals if s['pattern_A_signal'])
    n_v80_wl = sum(1 for s in signals if s['pattern_C_signal'])
    n_yf = sum(1 for s in signals if s['yf_available'])
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO daily_summary VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
              (date_str, regime, n_v80_entry, n_v80_wl, n_yf,
               counts.get('A_hold_back', 0), counts.get('B_exit_early', 0), counts.get('C_promote', 0),
               None))
    conn.commit()


def main():
    """매일 실행 — 최신 v80.6 ranking + 최신 yf data로 paper trade 신호 산출"""
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--v80-date', default=None, help='v80.6 ranking date YYYYMMDD (default: latest)')
    ap.add_argument('--yf-date', default=None, help='yf data date YYYYMMDD (default: latest)')
    args = ap.parse_args()

    conn = init_db()
    result = analyze_day(args.v80_date, args.yf_date)
    if not result:
        print('분석 실패')
        return
    signals, counts, regime = result

    save_signals(conn, signals, regime)
    save_summary(conn, signals[0]['date'], regime, signals, counts)

    # 콘솔 보고
    print(f'\n=== Paper Trade 결과 ({signals[0]["date"]}, regime={regime}) ===')
    print(f'\n[패턴 A — 진입 이중 검증]')
    a_entry = [s for s in signals if s['pattern_A_signal'] == 'enter']
    a_hold = [s for s in signals if s['pattern_A_signal'] == 'hold_back']
    a_noyf = [s for s in signals if s['pattern_A_signal'] == 'no_yf']
    print(f'  v80.6 entry 후보 중:')
    for s in (a_entry + a_hold + a_noyf):
        flag = {'enter': '✓ 매수', 'hold_back': '⚠️ 보류', 'no_yf': '? yf 데이터 없음'}[s['pattern_A_signal']]
        ntm = f'{s["ntm_score"]:+.3f}' if s['ntm_score'] is not None else 'N/A'
        print(f'    {s["ticker"]} {s["name"][:12]:<13} rank={s["v80_rank"]} NTM={ntm}  {flag}')

    print(f'\n[패턴 B — 조기 매도 (v80.6 보유 가정)]')
    b_exit = [s for s in signals if s['pattern_B_signal'] == 'exit_early']
    if b_exit:
        for s in b_exit:
            print(f'    ⚠️ 조기 매도: {s["ticker"]} {s["name"][:12]} rank={s["v80_rank"]} NTM={s["ntm_score"]:+.3f}')
    else:
        print(f'    조기 매도 신호 없음 (보유 후보 {sum(1 for s in signals if s["pattern_B_signal"]=="hold")} 종목 모두 yf 정상)')

    print(f'\n[패턴 C — Watchlist 격상]')
    c_promote = [s for s in signals if s['pattern_C_signal'] == 'promote']
    if c_promote:
        for s in c_promote:
            print(f'    ★ 격상: {s["ticker"]} {s["name"][:12]} rank={s["v80_rank"]} NTM={s["ntm_score"]:+.3f}')
    else:
        print(f'    격상 신호 없음')

    print(f'\n[요약] {signals[0]["date"]}')
    print(f'  yf 가용: {sum(1 for s in signals if s["yf_available"])}/{len(signals)}')
    print(f'  A_hold_back: {counts["A_hold_back"]}, B_exit_early: {counts["B_exit_early"]}, C_promote: {counts["C_promote"]}')
    print(f'\n저장: {DB_PATH}')


if __name__ == '__main__':
    main()
