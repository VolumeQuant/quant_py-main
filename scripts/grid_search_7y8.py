"""Phase 4: 그리드서치 + 안정성 + WF (Top 10 대상)

state/bt_7y8/ 기반으로 v77.1 vs 다른 전략 탐색:
- 4a: Attack 가중치 그리드 (~2000) + Defense 그리드 (~1000)
- 4b: Top 20 각 × E/X/S (60) = 1200
- 4c: 국면 규칙 확인일수/버퍼/쿨다운 (30)
- 4d: Top 10 × 25 이웃 안정성 (250)
- 4e: Top 10 × 4 WF 기간 (40)
- v77.1 baseline 비교

결과: backtest_results/grid_7y8_final.json
"""
import os, sys, json, time, glob, traceback
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor

sys.stdout.reconfigure(encoding='utf-8')
PROJECT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / 'backtest'))

import pandas as pd
import numpy as np

CACHE_DIR = PROJECT / 'data_cache'
BT_DIR = PROJECT / 'state' / 'bt_7y8'
BT_DEF_DIR = PROJECT / 'state' / 'bt_7y8' / 'defense'
RESULTS_DIR = PROJECT / 'backtest_results'
RESULTS_DIR.mkdir(exist_ok=True)
LOG_DIR = PROJECT / 'logs'
LOG_DIR.mkdir(exist_ok=True)

CHECKPOINT = RESULTS_DIR / 'grid_7y8_final.json'


def log(msg):
    ts = time.strftime('%H:%M:%S')
    print(f'[{ts}] {msg}', flush=True)
    with open(LOG_DIR / 'phase4_grid.log', 'a', encoding='utf-8') as f:
        f.write(f'[{ts}] {msg}\n')


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
        log(f'텔레그램 실패: {e}')


def load_bt_rankings(ranking_dir):
    data = {}
    for f in sorted(ranking_dir.glob('ranking_*.json')):
        d = f.stem.replace('ranking_','')
        if len(d) != 8: continue
        with open(f, 'r', encoding='utf-8') as fh:
            rd = json.load(fh)
            data[d] = rd.get('rankings', rd) if isinstance(rd, dict) else rd
    return data


def load_prices():
    files = sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'))
    if not files:
        raise FileNotFoundError('OHLCV 캐시 없음')
    return pd.read_parquet(files[-1]).replace(0, np.nan)


def load_kospi_ma():
    kospi = pd.read_parquet(CACHE_DIR / 'kospi_yf.parquet').iloc[:, 0].dropna()
    ma200 = kospi.rolling(200).mean()
    return kospi, ma200


def run_sim(tsim, runner, v, q, g, m, g_rev, entry, exit_p, slots,
            mom_type='12m-1m', g_sub1='rev_z', g_sub2='oca_z',
            g_sub3=None, g_w1=None, g_w2=None, g_w3=None,
            stop_loss=-0.10, trailing_stop=-0.15):
    """단일 시뮬레이션 실행"""
    from turbo_simulator import TurboRunner
    tsim._ensure_cache(v/100, q/100, g/100, m/100, g_rev, 20, mom_type,
                       g_sub1, g_sub2, g_sub3, g_w1, g_w2, g_w3)
    if runner is None:
        runner = TurboRunner(tsim)
    return runner.run(entry, exit_p, slots, stop_loss=stop_loss, trailing_stop=trailing_stop)


# ============================================================
# 4a: Attack 가중치 그리드 + Defense 그리드
# ============================================================
def phase_4a(tsim_boost, tsim_def, regime_dict=None):
    """국면전환 없이 단독 BT로 가중치 그리드 서치"""
    log('[4a] Attack + Defense 가중치 그리드 시작')
    t0 = time.time()
    from turbo_simulator import TurboRunner

    # Attack 그리드 (V5-30 × Q0-10 × G40-70 × M20-40) × G서브 3종
    attack_combos = []
    for v in range(0, 35, 5):
        for q in range(0, 15, 5):
            for g in range(30, 75, 5):
                m = 100 - v - q - g
                if 20 <= m <= 45:
                    # 3 G 서브팩터 변형
                    for g_sub3_name in ['gp_growth_z', 'op_margin_z', None]:
                        attack_combos.append({
                            'v': v, 'q': q, 'g': g, 'm': m,
                            'g_sub1': 'rev_z', 'g_sub2': 'oca_z',
                            'g_sub3': g_sub3_name,
                            'g_w1': 0.5, 'g_w2': 0.3, 'g_w3': 0.2 if g_sub3_name else None,
                            'g_rev': 0.0 if g_sub3_name else 0.7,
                            'mom_type': '12m-1m',
                        })
    log(f'  Attack 조합: {len(attack_combos)}')

    # Defense 그리드 (V20-35 × Q0-15 × G5-25 × M40-60)
    defense_combos = []
    for v in range(15, 40, 5):
        for q in range(0, 20, 5):
            for g in range(5, 30, 5):
                m = 100 - v - q - g
                if 40 <= m <= 65:
                    for g_sub12 in [('rev_accel_z', 'op_margin_z', 0.5),
                                    ('rev_z', 'oca_z', 0.7)]:
                        defense_combos.append({
                            'v': v, 'q': q, 'g': g, 'm': m,
                            'g_sub1': g_sub12[0], 'g_sub2': g_sub12[1],
                            'g_sub3': None, 'g_w1': None, 'g_w2': None, 'g_w3': None,
                            'g_rev': g_sub12[2],
                            'mom_type': '6m-1m',
                        })
    log(f'  Defense 조합: {len(defense_combos)}')

    # Attack 시뮬 (entry=7, exit=8, slots=3)
    attack_results = []
    runner = TurboRunner(tsim_boost)
    for i, c in enumerate(attack_combos):
        try:
            r = run_sim(tsim_boost, runner, c['v'], c['q'], c['g'], c['m'], c['g_rev'],
                        7, 8, 3, c['mom_type'], c['g_sub1'], c['g_sub2'],
                        c['g_sub3'], c['g_w1'], c['g_w2'], c['g_w3'])
            attack_results.append({**c, **r, 'mode': 'attack'})
        except Exception as e:
            pass
        if (i+1) % 200 == 0:
            log(f'  Attack {i+1}/{len(attack_combos)}')

    attack_results.sort(key=lambda x: x.get('calmar', 0), reverse=True)
    log(f'  Attack Top 5: {[(r["v"], r["q"], r["g"], r["m"], r["g_sub3"], round(r.get("calmar",0),2)) for r in attack_results[:5]]}')

    # Defense 시뮬 (entry=3, exit=6, slots=7)
    defense_results = []
    runner_d = TurboRunner(tsim_def)
    for i, c in enumerate(defense_combos):
        try:
            r = run_sim(tsim_def, runner_d, c['v'], c['q'], c['g'], c['m'], c['g_rev'],
                        3, 6, 7, c['mom_type'], c['g_sub1'], c['g_sub2'],
                        c['g_sub3'], c['g_w1'], c['g_w2'], c['g_w3'])
            defense_results.append({**c, **r, 'mode': 'defense'})
        except Exception:
            pass
        if (i+1) % 200 == 0:
            log(f'  Defense {i+1}/{len(defense_combos)}')

    defense_results.sort(key=lambda x: x.get('calmar', 0), reverse=True)
    log(f'  Defense Top 5: {[(r["v"], r["q"], r["g"], r["m"], round(r.get("calmar",0),2)) for r in defense_results[:5]]}')

    elapsed = (time.time() - t0) / 60
    log(f'[4a] 완료 {elapsed:.1f}분')
    return attack_results[:20], defense_results[:20]


# ============================================================
# 4b: E/X/S 규칙 (Top 10 × 60 규칙)
# ============================================================
def phase_4b(top_attack, top_defense, tsim_boost, tsim_def):
    log('[4b] E/X/S 규칙 서치')
    t0 = time.time()
    from turbo_simulator import TurboRunner

    rules = []
    for e in [3, 5, 7, 10]:
        for x_diff in [1, 3, 5]:
            x = e + x_diff
            for s in [3, 5, 7]:
                rules.append((e, x, s))

    def run_rules(combos, tsim, mode='attack'):
        results = []
        runner = TurboRunner(tsim)
        for c in combos:
            for (e, x, s) in rules:
                try:
                    r = run_sim(tsim, runner, c['v'], c['q'], c['g'], c['m'], c['g_rev'],
                                e, x, s, c['mom_type'], c['g_sub1'], c['g_sub2'],
                                c['g_sub3'], c['g_w1'], c['g_w2'], c['g_w3'])
                    results.append({**c, 'entry': e, 'exit': x, 'slots': s, **r, 'mode': mode})
                except Exception:
                    pass
        return results

    attack_rules = run_rules(top_attack[:10], tsim_boost, 'attack')
    attack_rules.sort(key=lambda x: x.get('calmar', 0), reverse=True)
    defense_rules = run_rules(top_defense[:10], tsim_def, 'defense')
    defense_rules.sort(key=lambda x: x.get('calmar', 0), reverse=True)

    elapsed = (time.time() - t0) / 60
    log(f'[4b] 완료 {elapsed:.1f}분, Attack Top1={round(attack_rules[0]["calmar"],2)}, Defense Top1={round(defense_rules[0]["calmar"],2)}')
    return attack_rules[:10], defense_rules[:10]


# ============================================================
# 4c: 국면 규칙 (run_regime 사용)
# ============================================================
def phase_4c(top_a, top_d, tsim_boost_d, kospi, ma200):
    """Top combo × Top defense × 국면 규칙 변형"""
    log('[4c] 국면 규칙 서치')
    t0 = time.time()
    from turbo_simulator import TurboRunner

    # 확인일수 변형 (5일 기본)
    regime_variants = []
    for conf in [3, 5, 7, 10]:
        regime_variants.append({'name': f'KP_MA200_{conf}d', 'conf': conf, 'buffer': 0})
    for buf in [0.01, 0.02]:
        regime_variants.append({'name': f'KP_MA200_5d_buf{int(buf*100)}', 'conf': 5, 'buffer': buf})

    def compute_regime_dict(conf_days, buffer_pct=0):
        reg = {}
        md = False; stk = 0; ss = False
        dates = sorted(set(tsim_boost_d.dates))
        for d in dates:
            ts = pd.Timestamp(d)
            kv = kospi.get(ts); mv = ma200.get(ts)
            if kv is not None and mv is not None:
                if buffer_pct > 0:
                    s = (kv > mv * (1 + buffer_pct)) if (kv > mv) else (kv < mv * (1 - buffer_pct) if kv < mv else ss)
                else:
                    s = kv > mv
            else:
                s = md
            if s == ss: stk += 1
            else: stk = 1; ss = s
            if stk >= conf_days and md != s: md = s
            reg[d] = 'boost' if md else 'defense'
        return reg

    # Top 5 attack × Top 5 defense × 6 규칙
    regime_results = []
    for rv in regime_variants:
        regime_dict = compute_regime_dict(rv['conf'], rv['buffer'])
        for ia, ca in enumerate(top_a[:5]):
            for id_, cd in enumerate(top_d[:5]):
                try:
                    r = tsim_boost_d.run_regime(
                        defense_params=(cd['v']/100, cd['q']/100, cd['g']/100, cd['m']/100, cd['g_rev'],
                                        cd.get('entry', 3), cd.get('exit', 6), cd.get('slots', 7)),
                        offense_params=(ca['v']/100, ca['q']/100, ca['g']/100, ca['m']/100, ca['g_rev'],
                                        ca.get('entry', 7), ca.get('exit', 8), ca.get('slots', 3)),
                        regime_dict=regime_dict,
                        g_sub1_d=cd['g_sub1'], g_sub2_d=cd['g_sub2'],
                        g_sub1_o=ca['g_sub1'], g_sub2_o=ca['g_sub2'],
                        g_sub3_o=ca['g_sub3'], g_w1_o=ca['g_w1'], g_w2_o=ca['g_w2'], g_w3_o=ca['g_w3'],
                    )
                    regime_results.append({
                        'regime': rv['name'], 'attack_idx': ia, 'defense_idx': id_,
                        'attack': ca, 'defense': cd, **r,
                    })
                except Exception as e:
                    log(f'  regime 오류 {rv["name"]} a={ia} d={id_}: {e}')

    regime_results.sort(key=lambda x: x.get('calmar', 0), reverse=True)
    elapsed = (time.time() - t0) / 60
    log(f'[4c] 완료 {elapsed:.1f}분, Top1 Cal={round(regime_results[0]["calmar"],2)}')
    return regime_results[:10]


# ============================================================
# 4d: 안정성 (Top 10 × 25 이웃)
# ============================================================
def phase_4d(top10_regime, tsim_boost_d, kospi, ma200):
    log('[4d] 인접 안정성 (Top 10 × 25 이웃)')
    t0 = time.time()

    def gen_neighbors(ca, cd, n=25):
        """가중치 ±5 이웃"""
        neighbors = []
        for dv in [-5, 0, 5]:
            for dg in [-5, 0, 5]:
                for dm in [-5, 0, 5]:
                    nv = max(0, ca['v'] + dv)
                    ng = max(5, ca['g'] + dg)
                    nm = max(15, ca['m'] + dm)
                    if abs(nv + ca['q'] + ng + nm - 100) > 5: continue
                    neighbors.append({**ca, 'v': nv, 'g': ng, 'm': nm})
                    if len(neighbors) >= n: break
                if len(neighbors) >= n: break
            if len(neighbors) >= n: break
        return neighbors[:n]

    stability_results = []
    for i, best in enumerate(top10_regime):
        ca = best['attack']; cd = best['defense']
        regime_name = best['regime']
        conf = int(regime_name.split('_')[-1].replace('d','').split('buf')[0] or 5)
        buf = int(regime_name.split('buf')[-1]) / 100 if 'buf' in regime_name else 0

        # 이웃 생성 (attack만 변경, defense 고정)
        neighbors = gen_neighbors(ca, cd)
        # 각 이웃 시뮬
        neighbor_cals = []
        # regime_dict 재사용
        reg = {}
        md=False; stk=0; ss=False
        for d in sorted(set(tsim_boost_d.dates)):
            ts = pd.Timestamp(d)
            kv = kospi.get(ts); mv = ma200.get(ts)
            s = (kv > mv) if kv is not None and mv is not None else md
            if s == ss: stk += 1
            else: stk = 1; ss = s
            if stk >= conf and md != s: md = s
            reg[d] = 'boost' if md else 'defense'

        for nb in neighbors:
            try:
                r = tsim_boost_d.run_regime(
                    defense_params=(cd['v']/100, cd['q']/100, cd['g']/100, cd['m']/100, cd['g_rev'],
                                    cd.get('entry', 3), cd.get('exit', 6), cd.get('slots', 7)),
                    offense_params=(nb['v']/100, nb['q']/100, nb['g']/100, nb['m']/100, nb['g_rev'],
                                    nb.get('entry', 7), nb.get('exit', 8), nb.get('slots', 3)),
                    regime_dict=reg,
                    g_sub1_d=cd['g_sub1'], g_sub2_d=cd['g_sub2'],
                    g_sub1_o=nb['g_sub1'], g_sub2_o=nb['g_sub2'],
                    g_sub3_o=nb['g_sub3'], g_w1_o=nb['g_w1'], g_w2_o=nb['g_w2'], g_w3_o=nb['g_w3'],
                )
                neighbor_cals.append(r.get('calmar', 0))
            except Exception:
                pass

        stab_ratio = sum(1 for c in neighbor_cals if c >= best['calmar'] * 0.7) / max(len(neighbor_cals), 1)
        min_cal = min(neighbor_cals) if neighbor_cals else 0
        stability_results.append({
            'rank': i+1, 'base_calmar': round(best['calmar'], 3),
            'stability_ratio': round(stab_ratio, 3), 'min_calmar': round(min_cal, 3),
            'neighbor_count': len(neighbor_cals), 'config': best,
        })

    elapsed = (time.time() - t0) / 60
    log(f'[4d] 완료 {elapsed:.1f}분')
    return stability_results


# ============================================================
# 4e: Walk-Forward (Top 10 × 4 기간)
# ============================================================
def phase_4e(top10, boost_rankings, defense_rankings, prices, kospi, ma200):
    log('[4e] Walk-Forward (Top 10 × 4 기간)')
    t0 = time.time()
    from turbo_simulator import TurboSimulator

    periods = [
        ('2018-2019', '20180702', '20191231'),
        ('2020-2021', '20200101', '20211231'),
        ('2022-2023', '20220101', '20231231'),
        ('2024-2026', '20240101', '20260414'),
    ]

    wf_results = []
    for pname, ps, pe in periods:
        # 기간 필터
        p_boost = {d: v for d, v in boost_rankings.items() if ps <= d <= pe}
        p_defense = {d: v for d, v in defense_rankings.items() if ps <= d <= pe}
        p_dates = sorted(p_boost.keys())
        if len(p_dates) < 50:
            log(f'  {pname}: 데이터 부족 ({len(p_dates)}일)')
            continue
        tsim_p = TurboSimulator(p_boost, p_dates, prices)
        tsim_p_d = TurboSimulator(p_defense, p_dates, prices)

        reg = {}
        md=False; stk=0; ss=False
        for d in p_dates:
            ts = pd.Timestamp(d)
            kv = kospi.get(ts); mv = ma200.get(ts)
            s = (kv > mv) if kv is not None and mv is not None else md
            if s == ss: stk += 1
            else: stk = 1; ss = s
            if stk >= 5 and md != s: md = s
            reg[d] = 'boost' if md else 'defense'

        for i, item in enumerate(top10):
            cfg = item.get('config', item)
            ca = cfg.get('attack', cfg); cd = cfg.get('defense', cfg)
            try:
                # 병합된 tsim 필요 — 우선 attack-only 버전
                r = tsim_p.run_regime(
                    defense_params=(cd['v']/100, cd['q']/100, cd['g']/100, cd['m']/100, cd['g_rev'],
                                    cd.get('entry', 3), cd.get('exit', 6), cd.get('slots', 7)),
                    offense_params=(ca['v']/100, ca['q']/100, ca['g']/100, ca['m']/100, ca['g_rev'],
                                    ca.get('entry', 7), ca.get('exit', 8), ca.get('slots', 3)),
                    regime_dict=reg,
                    g_sub1_d=cd['g_sub1'], g_sub2_d=cd['g_sub2'],
                    g_sub1_o=ca['g_sub1'], g_sub2_o=ca['g_sub2'],
                    g_sub3_o=ca.get('g_sub3'), g_w1_o=ca.get('g_w1'), g_w2_o=ca.get('g_w2'), g_w3_o=ca.get('g_w3'),
                )
                wf_results.append({'period': pname, 'rank': i+1, 'calmar': r.get('calmar', 0)})
            except Exception:
                wf_results.append({'period': pname, 'rank': i+1, 'calmar': 0, 'error': True})

    elapsed = (time.time() - t0) / 60
    log(f'[4e] 완료 {elapsed:.1f}분')
    return wf_results


# ============================================================
# 메인
# ============================================================
def main():
    log('=== Phase 4 그리드서치 시작 ===')
    send_tg('[Phase 4] 그리드서치 + 안정성 + WF 시작 (예상 25분)')
    t0 = time.time()

    try:
        log('데이터 로딩...')
        boost_rankings = load_bt_rankings(BT_DIR)
        defense_rankings = load_bt_rankings(BT_DEF_DIR)
        log(f'  boost {len(boost_rankings)}, defense {len(defense_rankings)}')

        if not boost_rankings or not defense_rankings:
            raise RuntimeError('bt_7y8 랭킹 파일 없음')

        prices = load_prices()
        kospi, ma200 = load_kospi_ma()

        from turbo_simulator import TurboSimulator
        dates = sorted(boost_rankings.keys())
        tsim_boost = TurboSimulator(boost_rankings, dates, prices)
        tsim_def = TurboSimulator(defense_rankings, dates, prices)

        # 4a + 4b
        top_a, top_d = phase_4a(tsim_boost, tsim_def)
        top_a2, top_d2 = phase_4b(top_a, top_d, tsim_boost, tsim_def)

        # 4c 국면 서치 (Attack 랭킹 기반 tsim 재사용)
        top_regime = phase_4c(top_a2, top_d2, tsim_boost, kospi, ma200)

        # 4d 안정성
        stability = phase_4d(top_regime, tsim_boost, kospi, ma200)

        # 4e WF
        wf = phase_4e(top_regime, boost_rankings, defense_rankings, prices, kospi, ma200)

        # === 다수 baseline 계산 (이전 버전 EDA 반영) ===
        log('baseline 계산: v77, v77.1, v78, attack-only, V20Q0G50M30')
        baselines = {}

        # 1) v77 (KP_MA200_5d, no crash cash)
        v77_a = {'v': 5, 'q': 0, 'g': 65, 'm': 30, 'g_rev': 0.0,
                 'g_sub1': 'rev_z', 'g_sub2': 'oca_z', 'g_sub3': 'gp_growth_z',
                 'g_w1': 0.5, 'g_w2': 0.3, 'g_w3': 0.2, 'mom_type': '12m-1m'}
        v77_d = {'v': 30, 'q': 5, 'g': 10, 'm': 55, 'g_rev': 0.5,
                 'g_sub1': 'rev_accel_z', 'g_sub2': 'op_margin_z', 'g_sub3': None,
                 'g_w1': None, 'g_w2': None, 'g_w3': None, 'mom_type': '6m-1m'}
        reg77 = {}
        md=False; stk=0; ss=False
        for d in dates:
            ts = pd.Timestamp(d)
            kv = kospi.get(ts); mv = ma200.get(ts)
            s = (kv > mv) if kv is not None and mv is not None else md
            if s == ss: stk += 1
            else: stk = 1; ss = s
            if stk >= 5 and md != s: md = s
            reg77[d] = 'boost' if md else 'defense'

        try:
            v77_r = tsim_boost.run_regime(
                defense_params=(0.30, 0.05, 0.10, 0.55, 0.5, 3, 6, 7),
                offense_params=(0.05, 0.00, 0.65, 0.30, 0.0, 7, 8, 3),
                regime_dict=reg77,
                g_sub1_d='rev_accel_z', g_sub2_d='op_margin_z',
                g_sub1_o='rev_z', g_sub2_o='oca_z',
                g_sub3_o='gp_growth_z', g_w1_o=0.5, g_w2_o=0.3, g_w3_o=0.2,
            )
            baselines['v77'] = v77_r
            log(f'  v77: Cal={v77_r.get("calmar", 0):.2f}, CAGR={v77_r.get("cagr", 0):.1f}%, MDD={v77_r.get("mdd", 0):.1f}%')
        except Exception as e:
            log(f'  v77 실패: {e}')

        # 2) v78 (7.8년 BT 결과 비교용)
        try:
            v78_r = tsim_boost.run_regime(
                defense_params=(0.30, 0.15, 0.25, 0.30, 0.7, 3, 4, 5),
                offense_params=(0.20, 0.00, 0.45, 0.35, 0.0, 10, 11, 5),
                regime_dict=reg77,
                g_sub1_d='rev_z', g_sub2_d='oca_z',
                g_sub1_o='rev_z', g_sub2_o='oca_z',
                g_sub3_o='op_margin_z', g_w1_o=0.5, g_w2_o=0.3, g_w3_o=0.2,
            )
            baselines['v78'] = v78_r
            log(f'  v78: Cal={v78_r.get("calmar", 0):.2f}, CAGR={v78_r.get("cagr", 0):.1f}%')
        except Exception as e:
            log(f'  v78 실패: {e}')

        # 3) attack-only (v78 EDA에서 7.8년 Cal 2.19로 KP_MA200_5d 1.34 이김)
        try:
            reg_all_boost = {d: 'boost' for d in dates}
            att_only = tsim_boost.run_regime(
                defense_params=(0.05, 0.00, 0.65, 0.30, 0.0, 7, 8, 3),  # placeholder
                offense_params=(0.05, 0.00, 0.65, 0.30, 0.0, 7, 8, 3),
                regime_dict=reg_all_boost,
                g_sub1_d='rev_z', g_sub2_d='oca_z',
                g_sub1_o='rev_z', g_sub2_o='oca_z',
                g_sub3_o='gp_growth_z', g_w1_o=0.5, g_w2_o=0.3, g_w3_o=0.2,
            )
            baselines['attack_only_v77'] = att_only
            log(f'  attack-only v77: Cal={att_only.get("calmar", 0):.2f}')
        except Exception as e:
            log(f'  attack-only 실패: {e}')

        # 4) V20Q0G50M30 + attack-only (v78 EDA에서 7.8년 Cal 2.19 최적)
        try:
            att_opt = tsim_boost.run_regime(
                defense_params=(0.20, 0.00, 0.50, 0.30, 0.0, 7, 8, 3),
                offense_params=(0.20, 0.00, 0.50, 0.30, 0.0, 7, 8, 3),
                regime_dict={d: 'boost' for d in dates},
                g_sub1_d='rev_z', g_sub2_d='oca_z',
                g_sub1_o='rev_z', g_sub2_o='oca_z',
                g_sub3_o='gp_growth_z', g_w1_o=0.5, g_w2_o=0.3, g_w3_o=0.2,
            )
            baselines['V20Q0G50M30_attack_only'] = att_opt
            log(f'  V20Q0G50M30(attack-only): Cal={att_opt.get("calmar", 0):.2f}')
        except Exception as e:
            log(f'  V20Q0G50M30 실패: {e}')

        # 저장
        results = {
            'baselines': baselines,
            'v77_baseline': baselines.get('v77', {}),
            'top10_regime': top_regime,
            'stability_top10': stability,
            'wf_top10': wf,
            'elapsed_min': (time.time() - t0) / 60,
        }
        with open(CHECKPOINT, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2, default=str)

        elapsed = (time.time() - t0) / 60
        log(f'[Phase 4] 완료 {elapsed:.1f}분, 결과: {CHECKPOINT.name}')
        send_tg(f'[Phase 4] 완료 ({elapsed:.1f}분)\nTop1 Cal={round(top_regime[0]["calmar"],2)}, v77.1 Cal={round(v77_r.get("calmar",0),2)}')
        return True

    except Exception as e:
        log(f'오류: {e}')
        log(traceback.format_exc())
        send_tg(f'[Phase 4] 실패: {e}')
        return False


if __name__ == '__main__':
    ok = main()
    sys.exit(0 if ok else 1)
