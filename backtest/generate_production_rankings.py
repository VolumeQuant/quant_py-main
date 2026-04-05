"""BT 랭킹에서 프로덕션 state/ 랭킹 재생성 — 시작일부터 전체

BT 랭킹(bt_v75/)의 factor sub-scores에 국면별 가중치를 적용해서
state/ ranking JSON 생성.

Usage:
    python backtest/generate_production_rankings.py
"""
import sys, json, time, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
sys.path.insert(0, 'backtest')

import pandas as pd
import numpy as np
from pathlib import Path

PROJECT = Path(__file__).parent.parent
STATE_DIR = PROJECT / 'state'
BT_DIR = PROJECT / 'backtest' / 'bt_v75'
CACHE_DIR = PROJECT / 'data_cache'

# v75 확정 파라미터
DEFENSE_PARAMS = {
    'V_W': 0.20, 'Q_W': 0.10, 'G_W': 0.20, 'M_W': 0.50,
    'G_REV': 0.6, 'MOM': '6m-1m',
    'ENTRY': 5, 'EXIT': 8, 'SLOTS': 7,
}
OFFENSE_PARAMS = {
    'V_W': 0.25, 'Q_W': 0.00, 'G_W': 0.50, 'M_W': 0.25,
    'G_REV': 0.3, 'MOM': '12m-1m',
    'ENTRY': 3, 'EXIT': 4, 'SLOTS': 7,
}
CONFIRM_DAYS = 3


def compute_regime_per_day(dates):
    """KP120_3d + VIX25: KOSPI > MA120 AND VIX < 25, 3일 확인"""
    kospi = pd.read_parquet(CACHE_DIR / 'kospi_yf.parquet').iloc[:, 0]
    vix = pd.read_parquet(CACHE_DIR / 'vix_daily.parquet').iloc[:, 0]
    kp_ma120 = kospi.rolling(120).mean()

    # 일별 raw signal
    raw_signal = {}
    for d in dates:
        dt = pd.Timestamp(d)
        kp_prev = kospi[kospi.index < dt]
        vix_prev = vix[vix.index < dt]
        ma_prev = kp_ma120[kp_ma120.index < dt]
        if kp_prev.empty or vix_prev.empty or ma_prev.empty:
            raw_signal[d] = False
            continue
        kp_val = kp_prev.iloc[-1]
        vix_val = vix_prev.iloc[-1]
        ma_val = ma_prev.iloc[-1]
        if pd.isna(kp_val) or pd.isna(vix_val) or pd.isna(ma_val):
            raw_signal[d] = False
            continue
        raw_signal[d] = (kp_val > ma_val) and (vix_val < 25)

    # 3일 확인
    regime = {}
    mode = False  # False=defense, True=boost
    streak = 0
    streak_dir = False
    for d in dates:
        sig = raw_signal.get(d, False)
        if sig == streak_dir:
            streak += 1
        else:
            streak = 1
            streak_dir = sig
        if streak >= CONFIRM_DAYS and mode != sig:
            mode = sig
        regime[d] = mode
    return regime


def reweight_ranking(bt_ranking, params):
    """BT 랭킹의 sub-scores에 가중치 적용 → composite score + rank"""
    mom_key = f"mom_{params['MOM'].replace('-','')}_s"  # mom_6m1m_s, mom_12m1m_s

    scored = []
    for r in bt_ranking:
        v_s = r.get('value_s', 0)
        q_s = r.get('quality_s', 0)
        # Growth re-standardization with g_rev
        rev_z = r.get('rev_z', 0)
        oca_z = r.get('oca_z', 0)
        g_rev = params['G_REV']
        g_raw = g_rev * rev_z + (1 - g_rev) * oca_z
        m_s = r.get(mom_key, r.get('momentum_s', 0))

        scored.append({
            'ticker': r.get('ticker', r.get('t', '')),
            'name': r.get('name', r.get('n', '')),
            'value_s': v_s, 'quality_s': q_s,
            'g_raw': g_raw, 'momentum_s': m_s,
            'rev_z': rev_z, 'oca_z': oca_z,
            'price': r.get('price', 0),
            'sector': r.get('sector', ''),
        })

    if not scored:
        return []

    # Growth re-standardize
    g_raws = [s['g_raw'] for s in scored]
    g_mean = np.mean(g_raws)
    g_std = np.std(g_raws)
    for s in scored:
        s['growth_s'] = (s['g_raw'] - g_mean) / g_std if g_std > 0 else 0

    # Composite score
    for s in scored:
        s['score'] = (params['V_W'] * s['value_s'] +
                      params['Q_W'] * s['quality_s'] +
                      params['G_W'] * s['growth_s'] +
                      params['M_W'] * s['momentum_s'])

    # Rank by score
    scored.sort(key=lambda x: -x['score'])
    for i, s in enumerate(scored):
        s['rank'] = i + 1
        s['composite_rank'] = i + 1

    return scored


def main():
    t0 = time.time()
    print('=== 프로덕션 state/ 랭킹 재생성 ===', flush=True)

    # BT 파일 목록
    bt_files = sorted(BT_DIR.glob('ranking_*.json'))
    dates = [f.stem.replace('ranking_', '') for f in bt_files]
    print(f'BT 기간: {dates[0]}~{dates[-1]} ({len(dates)}일)', flush=True)

    # 국면 계산
    print('국면 계산 (KP120_3d+VIX25)...', flush=True)
    regime = compute_regime_per_day(dates)
    boost_days = sum(1 for v in regime.values() if v)
    print(f'  Boost: {boost_days}/{len(dates)} ({100*boost_days/len(dates):.1f}%)', flush=True)

    # 기존 state/ 백업
    backup_dir = STATE_DIR / 'v75_pre_rebuild_backup'
    if not backup_dir.exists():
        backup_dir.mkdir(parents=True)
        import shutil
        for f in STATE_DIR.glob('ranking_*.json'):
            shutil.copy2(f, backup_dir / f.name)
        print(f'  기존 state/ 백업: {len(list(backup_dir.glob("*.json")))}개', flush=True)

    # state/ 기존 ranking 삭제
    for f in STATE_DIR.glob('ranking_*.json'):
        f.unlink()
    for f in STATE_DIR.glob('ranking_core_*.json'):
        f.unlink()

    # 일자별 생성
    success = 0
    for i, d in enumerate(dates):
        bt_file = BT_DIR / f'ranking_{d}.json'
        with open(bt_file, 'r', encoding='utf-8') as f:
            bt_data = json.load(f)

        bt_rankings = bt_data.get('rankings', [])
        is_boost = regime.get(d, False)
        params = OFFENSE_PARAMS if is_boost else DEFENSE_PARAMS
        mode_str = 'boost' if is_boost else 'defense'

        scored = reweight_ranking(bt_rankings, params)
        if not scored:
            continue

        # 3일 가중 순위 (T0×0.5 + T1×0.3 + T2×0.2)
        # 저장 (ranking_manager 호환 형식)
        output = {
            'date': d,
            'mode': mode_str,
            'params': {
                'V_W': params['V_W'], 'Q_W': params['Q_W'],
                'G_W': params['G_W'], 'M_W': params['M_W'],
                'G_REV': params['G_REV'], 'MOM': params['MOM'],
                'ENTRY': params['ENTRY'], 'EXIT': params['EXIT'], 'SLOTS': params['SLOTS'],
            },
            'rankings': [{
                'rank': s['rank'], 'composite_rank': s['composite_rank'],
                'ticker': s['ticker'], 'name': s['name'],
                'score': round(s['score'], 4),
                'value_s': round(s['value_s'], 4),
                'quality_s': round(s['quality_s'], 4),
                'growth_s': round(s['growth_s'], 4),
                'momentum_s': round(s['momentum_s'], 4),
                'rev_z': round(s['rev_z'], 4),
                'oca_z': round(s['oca_z'], 4),
                'price': s['price'],
                'sector': s['sector'],
            } for s in scored],
        }

        # ranking_{date}.json (send_telegram_auto 호환)
        out_file = STATE_DIR / f'ranking_{d}.json'
        with open(out_file, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False)
        success += 1

        if (i + 1) % 100 == 0:
            elapsed = time.time() - t0
            print(f'  [{i+1}/{len(dates)}] {elapsed:.0f}초 | mode={mode_str}', flush=True)

    print(f'\n완료: {success}/{len(dates)}일, {time.time()-t0:.1f}초', flush=True)

    # 최근 5일 확인
    print('\n최근 5일:')
    recent_files = sorted(STATE_DIR.glob('ranking_core_*.json'))[-5:]
    for f in recent_files:
        with open(f, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        n = len(data.get('rankings', []))
        mode = data.get('mode', '?')
        top3 = [(r['ticker'], r['name'][:6], round(r['score'], 3)) for r in data['rankings'][:3]]
        print(f'  {f.stem}: {mode} {n}종목 | Top3: {top3}')


if __name__ == '__main__':
    main()
