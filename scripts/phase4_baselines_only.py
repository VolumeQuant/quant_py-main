"""Phase 4 복구판 — 그리드서치 실패 시 baseline 비교만으로 진행

v77, v77.1, v78, attack-only v77, V20Q0G50M30 attack-only 5개 baseline 계산
결과 → backtest_results/grid_7y8_final.json (finalize_overnight.py가 참조)
"""
import os, sys, json, time, traceback
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

PROJECT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / 'backtest'))

import pandas as pd
import numpy as np

CACHE_DIR = PROJECT / 'data_cache'
BT_DIR = PROJECT / 'state' / 'bt_7y8'
BT_DEF = PROJECT / 'state' / 'bt_7y8' / 'defense'
RESULTS_DIR = PROJECT / 'backtest_results'
RESULTS_DIR.mkdir(exist_ok=True)


def log(msg):
    ts = time.strftime('%H:%M:%S')
    print(f'[{ts}] {msg}', flush=True)


def send_tg(msg):
    try:
        import requests
        from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID
        url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
        MAX = 4000
        for i in range(0, len(msg), MAX):
            requests.post(url, data={'chat_id': TELEGRAM_PRIVATE_ID, 'text': msg[i:i+MAX]}, timeout=30)
            time.sleep(0.3)
    except Exception as e:
        log(f'tg: {e}')


def load_rankings(d):
    data = {}
    for f in sorted(d.glob('ranking_*.json')):
        date = f.stem.replace('ranking_', '')
        if len(date) != 8: continue
        with open(f, 'r', encoding='utf-8') as fh:
            rd = json.load(fh)
        data[date] = rd.get('rankings', rd) if isinstance(rd, dict) else rd
    return data


def main():
    log('=== Phase 4 baselines 전용 ===')
    send_tg('[Phase 4 복구] baseline 5개 계산 시작')
    t0 = time.time()

    try:
        boost = load_rankings(BT_DIR)
        defense = load_rankings(BT_DEF)
        log(f'boost {len(boost)}, defense {len(defense)}')

        prices = pd.read_parquet(sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'))[-1]).replace(0, np.nan)
        kospi = pd.read_parquet(CACHE_DIR / 'kospi_yf.parquet').iloc[:, 0].dropna()
        ma200 = kospi.rolling(200).mean()

        from turbo_simulator import TurboSimulator, TurboRunner
        dates = sorted(boost.keys())
        tsim = TurboSimulator(boost, dates, prices)
        log(f'TurboSim 초기화 완료, {len(dates)}일')

        # 국면 판단 (KP_MA200_5d)
        reg = {}
        md = False; stk = 0; ss = False
        for d in dates:
            ts = pd.Timestamp(d)
            kv = kospi.get(ts); mv = ma200.get(ts)
            s = (kv > mv) if kv is not None and mv is not None else md
            if s == ss: stk += 1
            else: stk = 1; ss = s
            if stk >= 5 and md != s: md = s
            reg[d] = 'boost' if md else 'defense'

        baselines = {}

        def run_case(name, def_p, off_p, g_sub_d, g_sub_o, reg_dict):
            try:
                # def_p/off_p는 튜플 (v, q, g, m, g_rev, entry, exit, slots)
                # run_regime은 dict 요구 → 변환
                def_dict = {'v': def_p[0], 'q': def_p[1], 'g': def_p[2], 'm': def_p[3],
                            'g_rev': def_p[4], 'entry': def_p[5], 'exit': def_p[6], 'slots': def_p[7],
                            'mom': def_p[8] if len(def_p) > 8 else '6m-1m'}
                off_dict = {'v': off_p[0], 'q': off_p[1], 'g': off_p[2], 'm': off_p[3],
                            'g_rev': off_p[4], 'entry': off_p[5], 'exit': off_p[6], 'slots': off_p[7],
                            'mom': off_p[8] if len(off_p) > 8 else '12m-1m'}
                # regime_dict: 'boost'/'defense' 문자열을 True/False로 변환
                reg_bool = {d: (v == 'boost') for d, v in reg_dict.items()}
                r = tsim.run_regime(
                    defense_params=def_dict,
                    offense_params=off_dict,
                    regime_dict=reg_bool,
                    g_sub1_d=g_sub_d[0], g_sub2_d=g_sub_d[1],
                    g_sub1_o=g_sub_o[0], g_sub2_o=g_sub_o[1],
                    g_sub3_o=g_sub_o[2] if len(g_sub_o) > 2 else None,
                    g_w1_o=g_sub_o[3] if len(g_sub_o) > 3 else None,
                    g_w2_o=g_sub_o[4] if len(g_sub_o) > 4 else None,
                    g_w3_o=g_sub_o[5] if len(g_sub_o) > 5 else None,
                )
                baselines[name] = r
                log(f'  {name}: Cal={r.get("calmar", 0):.2f} CAGR={r.get("cagr", 0):.1f}% MDD={r.get("mdd", 0):.1f}%')
            except Exception as e:
                log(f'  {name} 실패: {e}')
                log(traceback.format_exc())

        # 1) v77 (KP_MA200_5d)
        run_case('v77',
                 def_p=(0.30, 0.05, 0.10, 0.55, 0.5, 3, 6, 7, '6m-1m'),
                 off_p=(0.05, 0.00, 0.65, 0.30, 0.0, 7, 8, 3, '12m-1m'),
                 g_sub_d=('rev_accel_z', 'op_margin_z'),
                 g_sub_o=('rev_z', 'oca_z', 'gp_growth_z', 0.5, 0.3, 0.2),
                 reg_dict=reg)

        # 2) v78 (KP_MA200_5d, 3f rev+oca+opm)
        run_case('v78',
                 def_p=(0.30, 0.15, 0.25, 0.30, 0.7, 3, 4, 5, '6m'),
                 off_p=(0.20, 0.00, 0.45, 0.35, 0.0, 10, 11, 5, '12m'),
                 g_sub_d=('rev_z', 'oca_z'),
                 g_sub_o=('rev_z', 'oca_z', 'op_margin_z', 0.5, 0.3, 0.2),
                 reg_dict=reg)

        # 3) attack-only v77 (공격만)
        run_case('attack_only_v77',
                 def_p=(0.05, 0.00, 0.65, 0.30, 0.0, 7, 8, 3, '12m-1m'),
                 off_p=(0.05, 0.00, 0.65, 0.30, 0.0, 7, 8, 3, '12m-1m'),
                 g_sub_d=('rev_z', 'oca_z'),
                 g_sub_o=('rev_z', 'oca_z', 'gp_growth_z', 0.5, 0.3, 0.2),
                 reg_dict={d: 'boost' for d in dates})

        # 4) V20Q0G50M30 attack-only
        run_case('V20Q0G50M30_attack_only',
                 def_p=(0.20, 0.00, 0.50, 0.30, 0.0, 7, 8, 3, '12m-1m'),
                 off_p=(0.20, 0.00, 0.50, 0.30, 0.0, 7, 8, 3, '12m-1m'),
                 g_sub_d=('rev_z', 'oca_z'),
                 g_sub_o=('rev_z', 'oca_z', 'gp_growth_z', 0.5, 0.3, 0.2),
                 reg_dict={d: 'boost' for d in dates})

        # 5) v78 attack-only (공격만)
        run_case('v78_attack_only',
                 def_p=(0.20, 0.00, 0.45, 0.35, 0.0, 10, 11, 5, '12m'),
                 off_p=(0.20, 0.00, 0.45, 0.35, 0.0, 10, 11, 5, '12m'),
                 g_sub_d=('rev_z', 'oca_z'),
                 g_sub_o=('rev_z', 'oca_z', 'op_margin_z', 0.5, 0.3, 0.2),
                 reg_dict={d: 'boost' for d in dates})

        # 결과 저장 (finalize가 읽는 포맷 맞춤)
        results = {
            'baselines': baselines,
            'v77_baseline': baselines.get('v77', {}),
            'top10_regime': [],  # 빈 리스트 (그리드서치 실패)
            'stability_top10': [],
            'wf_top10': [],
            'elapsed_min': (time.time() - t0) / 60,
            'grid_search_status': 'failed_baselines_only',
        }
        with open(RESULTS_DIR / 'grid_7y8_final.json', 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2, default=str)

        elapsed = (time.time() - t0) / 60
        log(f'완료 {elapsed:.1f}분')

        # 텔레그램 summary
        summary = f'''[Phase 4 복구 완료] {elapsed:.1f}분

7.8년 BT 성과 baseline:
'''
        for name, r in baselines.items():
            summary += f'\n{name}:\n  Cal={r.get("calmar", 0):.2f} CAGR={r.get("cagr", 0):.1f}% MDD={r.get("mdd", 0):.1f}%'
        send_tg(summary)
        return True

    except Exception as e:
        log(f'오류: {e}')
        log(traceback.format_exc())
        send_tg(f'[Phase 4 복구] 실패: {e}')
        return False


if __name__ == '__main__':
    ok = main()
    sys.exit(0 if ok else 1)
