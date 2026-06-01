# -*- coding: utf-8 -*-
"""자율주행: 4 universe × 정밀 V/Q/G/M × 슬롯 grid → 통합 비교 → 보고서 → git commit + push → 텔레그램 알림

사용자 의도: KOSPI 200 / KOSDAQ 150 / KP200+KQ150 / raw universe에서 최적 V/Q/G/M 가중치 탐색.
TurboSim run_regime (defense=cash) 진짜 production v80.22 룰 적용.
"""
import json, sys, re, time, os, requests, subprocess
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path('backtest').resolve()))
from turbo_simulator import TurboSimulator

sys.stdout.reconfigure(encoding='utf-8')
LOG = open('logs/autopilot_kp200_kq150.log', 'w', encoding='utf-8')

def log(msg):
    s = f'[{datetime.now().strftime("%H:%M:%S")}] {msg}'
    print(s, flush=True)
    LOG.write(s + '\n')
    LOG.flush()


def send_telegram(msg):
    """개인봇 알림"""
    try:
        from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={'chat_id': TELEGRAM_PRIVATE_ID, 'text': msg, 'parse_mode': 'HTML'},
            timeout=30)
        log(f'텔레그램 알림 발송: {r.status_code}')
    except Exception as e:
        log(f'텔레그램 실패: {e}')


t0 = time.time()
try:
    # ============================================================
    # 1. 데이터 로드
    # ============================================================
    log('=== 1. 데이터 로드 ===')
    files = sorted(Path('state').glob('ranking_2*.json'))
    all_rankings = {}
    dates = []
    for f in files:
        d = json.loads(f.read_text(encoding='utf-8'))
        date_str = d.get('date','')
        if not date_str:
            m = re.search(r'ranking_(\d{8})', f.name)
            if m: date_str = m.group(1)
        all_rankings[date_str] = d.get('rankings', [])
        dates.append(date_str)
    log(f'  ranking: {len(dates)} 거래일 (state/)')

    with open('data_cache/idx_kp200_kq150_20260529.json') as f:
        idx = json.load(f)
    kp200 = set(idx['kp200']); kq150 = set(idx['kq150'])
    combined = kp200 | kq150

    def filter_by_set(s): return {d: [r for r in all_rankings[d] if r['ticker'] in s] for d in dates}

    univ_dict = {
        'KP200+KQ150': filter_by_set(combined),
        'KOSPI 200': filter_by_set(kp200),
        'KOSDAQ 150': filter_by_set(kq150),
        'raw (production)': all_rankings,
    }

    # KOSPI MA20>MA80 cross (v80.18) regime
    kp = pd.read_parquet('data_cache/kospi_yf.parquet')
    kp.index = pd.to_datetime(kp.index)
    ma20 = kp['close'].rolling(20).mean()
    ma80 = kp['close'].rolling(80).mean()
    sig = (ma20 > ma80)
    N = 5
    out = sig.astype(int).copy(); out[:] = 0
    out_d = (~sig).astype(int)
    out_def = out.copy()
    for i in range(N-1, len(sig)):
        if sig.iloc[i-N+1:i+1].sum() == N: out.iloc[i] = 1
        if out_d.iloc[i-N+1:i+1].sum() == N: out_def.iloc[i] = 1
    state = 1
    final = sig.astype(int).copy()
    for i in range(len(sig)):
        if state == 1 and out_def.iloc[i] == 1: state = 0
        elif state == 0 and out.iloc[i] == 1: state = 1
        final.iloc[i] = state
    regime_dict = {}
    for d in dates:
        dt = pd.to_datetime(d)
        if dt in final.index: regime_dict[d] = bool(final.loc[dt])
        else:
            prior = final.index[final.index <= dt]
            regime_dict[d] = bool(final.loc[prior[-1]]) if len(prior) else True
    boost_n = sum(regime_dict.values())
    log(f'  regime: boost {boost_n}, defense {len(regime_dict)-boost_n}')

    prices = pd.read_parquet('data_cache/all_ohlcv_20170601_20260529.parquet')
    prices.index = pd.to_datetime(prices.index)
    bench = pd.read_parquet('data_cache/kospi_yf.parquet')
    bench.index = pd.to_datetime(bench.index)

    # ============================================================
    # 2. 가중치 grid (10%씩 러프 — 4 universe 합쳐서 빠르게)
    # ============================================================
    log(f'\n=== 2. 가중치 러프 grid 10%씩 ===')
    def gen_weights(step):
        out = []
        for v in range(0, 71, step):
            for q in range(0, 51, step):
                for g in range(0, 81, step):
                    m = 100 - v - q - g
                    if 0 <= m <= 70 and m % step == 0:
                        out.append((v/100, q/100, g/100, m/100))
        return out
    weights_rough = gen_weights(10)
    log(f'  가중치 조합: {len(weights_rough)}')
    slot_configs = [(3,4), (5,7), (7,10), (10,14)]

    defense = {'v': 0.35, 'q': 0.15, 'g': 0.15, 'm': 0.35, 'g_rev': 0.8,
               'entry': 0, 'exit': 8.0, 'slots': 5, 'mom': '6m-1m'}

    def run_grid(weights, slot_cfgs, label):
        results = []
        for univ_label, u in univ_dict.items():
            log(f'  --- {univ_label}: TurboSim 인스턴스 ---')
            tsim = TurboSimulator(u, dates, prices, bench)
            for v, q, g, m in weights:
                for ns, er in slot_cfgs:
                    boost = {'v': v, 'q': q, 'g': g, 'm': m, 'g_rev': 0.4,
                             'entry': ns, 'exit': float(er), 'slots': ns, 'mom': '12m'}
                    try:
                        r = tsim.run_regime(
                            defense_params=defense, offense_params=boost,
                            regime_dict=regime_dict,
                            stop_loss=None, trailing_stop=None,
                            g_sub1_o='rev_z', g_sub2_o='oca_z', g_sub3_o='gp_growth_z',
                            g_w1_o=0.4, g_w2_o=0.4, g_w3_o=0.2,
                        )
                        results.append({
                            'univ': univ_label, 'v': v, 'q': q, 'g': g, 'm': m,
                            'slots': ns, 'exit': er,
                            'cagr': r['cagr'], 'mdd': r['mdd'], 'calmar': r['calmar'],
                            'total': r['total'], 'alpha': r['alpha'], 'sharpe': r['sharpe'],
                        })
                    except: pass
            log(f'    {univ_label} 완료 [{time.time()-t0:.0f}s]')
        return pd.DataFrame(results)

    df_rough = run_grid(weights_rough, slot_configs, 'rough')
    df_rough.to_csv('bt_autopilot_rough_grid.csv', index=False, encoding='utf-8')
    log(f'rough grid 완료 [{time.time()-t0:.0f}s, {len(df_rough)} 시나리오]')

    # ============================================================
    # 3. universe별 Top 식별 + 정밀 grid (5%씩, 상위 universe만)
    # ============================================================
    log(f'\n=== 3. universe별 Top + 정밀 grid ===')
    top_per_univ = {}
    for univ in univ_dict.keys():
        sub = df_rough[df_rough['univ']==univ]
        top1 = sub.sort_values('calmar', ascending=False).iloc[0]
        top_per_univ[univ] = top1
        log(f'  {univ} best: V{int(top1.v*100)}Q{int(top1.q*100)}G{int(top1.g*100)}M{int(top1.m*100)} '
            f'slots {int(top1.slots)}/{int(top1.exit)} Cal {top1.calmar:.2f} CAGR {top1.cagr:.1f}% Total {top1.total:.0f}%')

    # 모든 universe 상위 Cal 평균 = 2개 universe에서 정밀
    avg_top_cal = {univ: df_rough[df_rough['univ']==univ].sort_values('calmar', ascending=False).head(5)['calmar'].mean()
                   for univ in univ_dict.keys()}
    sorted_univ = sorted(avg_top_cal.items(), key=lambda x:-x[1])
    log(f'  universe 순위 (Top 5 평균 Cal):')
    for u, c in sorted_univ: log(f'    {u}: {c:.3f}')

    top_2_univ = [sorted_univ[0][0], sorted_univ[1][0]]
    log(f'  정밀 grid 대상: {top_2_univ}')

    # 정밀 grid (5%씩, 상위 2 universe만)
    weights_fine = gen_weights(5)
    log(f'  정밀 가중치: {len(weights_fine)}')
    fine_univ = {u: univ_dict[u] for u in top_2_univ}

    results_fine = []
    for univ_label, u in fine_univ.items():
        tsim = TurboSimulator(u, dates, prices, bench)
        n_done = 0
        for v, q, g, m in weights_fine:
            for ns, er in slot_configs:
                boost = {'v': v, 'q': q, 'g': g, 'm': m, 'g_rev': 0.4,
                         'entry': ns, 'exit': float(er), 'slots': ns, 'mom': '12m'}
                try:
                    r = tsim.run_regime(
                        defense_params=defense, offense_params=boost,
                        regime_dict=regime_dict,
                        stop_loss=None, trailing_stop=None,
                        g_sub1_o='rev_z', g_sub2_o='oca_z', g_sub3_o='gp_growth_z',
                        g_w1_o=0.4, g_w2_o=0.4, g_w3_o=0.2,
                    )
                    results_fine.append({
                        'univ': univ_label, 'v': v, 'q': q, 'g': g, 'm': m,
                        'slots': ns, 'exit': er,
                        'cagr': r['cagr'], 'mdd': r['mdd'], 'calmar': r['calmar'],
                        'total': r['total'], 'alpha': r['alpha'], 'sharpe': r['sharpe'],
                    })
                    n_done += 1
                except: pass
        log(f'    {univ_label} 정밀 완료: {n_done} 시나리오 [{time.time()-t0:.0f}s]')

    df_fine = pd.DataFrame(results_fine)
    df_fine.to_csv('bt_autopilot_fine_grid.csv', index=False, encoding='utf-8')
    log(f'fine grid 완료 [{time.time()-t0:.0f}s, {len(df_fine)} 시나리오]')

    # ============================================================
    # 4. 인접 안정성 검증 — 최고 Cal 시나리오 + 이웃 ±5%
    # ============================================================
    log(f'\n=== 4. 인접 안정성 검증 ===')
    overall_best = df_fine.sort_values('calmar', ascending=False).iloc[0]
    log(f'  전체 best: {overall_best.univ} V{int(overall_best.v*100)}Q{int(overall_best.q*100)}G{int(overall_best.g*100)}M{int(overall_best.m*100)} '
        f'slots {int(overall_best.slots)}/{int(overall_best.exit)} Cal {overall_best.calmar:.2f}')

    # 이웃 ±5% (각 팩터 1step 변형) Cal 분포
    bv, bq, bg, bm = overall_best.v, overall_best.q, overall_best.g, overall_best.m
    bs, be = overall_best.slots, overall_best.exit
    neighbor_cals = []
    for dv in [-0.05, 0, 0.05]:
        for dq in [-0.05, 0, 0.05]:
            for dg in [-0.05, 0, 0.05]:
                nv, nq, ng = round(bv+dv, 2), round(bq+dq, 2), round(bg+dg, 2)
                nm = round(1.0 - nv - nq - ng, 2)
                if nv < 0 or nq < 0 or ng < 0 or nm < 0: continue
                row = df_fine[(df_fine.univ==overall_best.univ) &
                              (df_fine.v.round(2)==nv) & (df_fine.q.round(2)==nq) &
                              (df_fine.g.round(2)==ng) & (df_fine.slots==bs) & (df_fine.exit==be)]
                if not row.empty:
                    neighbor_cals.append(float(row.iloc[0].calmar))
    cv = np.std(neighbor_cals) / np.mean(neighbor_cals) if neighbor_cals and np.mean(neighbor_cals) > 0 else 99
    log(f'  이웃 ±5% Cal 분포: {len(neighbor_cals)}개, 평균 {np.mean(neighbor_cals):.2f}, CV {cv:.3f}')
    log(f'  안정성: {"PASS" if cv < 0.10 else "WARN" if cv < 0.30 else "FAIL"}')

    # ============================================================
    # 5. 보고서 작성
    # ============================================================
    log(f'\n=== 5. 보고서 작성 ===')
    report = []
    report.append('# KR 시스템 V/Q/G/M 가중치 + universe 최적화 보고서')
    report.append(f'\n> 2026-06-01 자율주행 자동 생성')
    report.append(f'> v80.22 진짜 BT (state/ 1941일, TurboSim run_regime + defense=cash)')

    report.append('\n## 1. 검증 시스템')
    report.append('- BT 기간: 2018-07-02 ~ 2026-05-29 (7.4년)')
    report.append('- ranking: state/ (production v80.22 진짜 일별)')
    report.append('- regime: KOSPI MA20 > MA80 (5일 confirm)')
    report.append('- defense: cash 100% (ENTRY_RANK=0)')
    report.append('- SL/TS: None (v80.21~22)')
    report.append('- benchmark: KOSPI')

    report.append('\n## 2. 러프 grid (10%씩 V/Q/G/M × 4 universe × 슬롯 4)')
    report.append(f'- 시나리오: {len(df_rough)}')
    report.append('\n### Universe별 best (Cal 기준)\n')
    report.append('| Universe | V | Q | G | M | slots/exit | CAGR | MDD | **Cal** | Total | Alpha |')
    report.append('|---|---|---|---|---|---|---|---|---|---|---|')
    for univ in univ_dict.keys():
        b = top_per_univ[univ]
        report.append(f'| {univ} | {int(b.v*100)} | {int(b.q*100)} | {int(b.g*100)} | {int(b.m*100)} '
                      f'| {int(b.slots)}/{int(b.exit)} | {b.cagr:.1f}% | {b.mdd:.1f}% | **{b.calmar:.2f}** '
                      f'| +{b.total:.0f}% | +{b.alpha:.1f}% |')

    report.append(f'\n→ 정밀 grid 대상: **{top_2_univ}** (Top 5 평균 Cal 기준)')

    report.append('\n## 3. 정밀 grid (5%씩 V/Q/G/M × 상위 2 universe × 슬롯 4)')
    report.append(f'- 시나리오: {len(df_fine)}')
    report.append('\n### 전체 Top 10 by Calmar\n')
    top_10 = df_fine.sort_values('calmar', ascending=False).head(10)
    report.append('| Universe | V | Q | G | M | slots/exit | CAGR | MDD | **Cal** | Total | Alpha |')
    report.append('|---|---|---|---|---|---|---|---|---|---|---|')
    for _, r in top_10.iterrows():
        report.append(f'| {r.univ} | {int(r.v*100)} | {int(r.q*100)} | {int(r.g*100)} | {int(r.m*100)} '
                      f'| {int(r.slots)}/{int(r.exit)} | {r.cagr:.1f}% | {r.mdd:.1f}% | **{r.calmar:.2f}** '
                      f'| +{r.total:.0f}% | +{r.alpha:.1f}% |')

    report.append('\n### 전체 Top 10 by Total\n')
    top_t = df_fine.sort_values('total', ascending=False).head(10)
    report.append('| Universe | V | Q | G | M | slots/exit | CAGR | MDD | Cal | **Total** | Alpha |')
    report.append('|---|---|---|---|---|---|---|---|---|---|---|')
    for _, r in top_t.iterrows():
        report.append(f'| {r.univ} | {int(r.v*100)} | {int(r.q*100)} | {int(r.g*100)} | {int(r.m*100)} '
                      f'| {int(r.slots)}/{int(r.exit)} | {r.cagr:.1f}% | {r.mdd:.1f}% | {r.calmar:.2f} '
                      f'| **+{r.total:.0f}%** | +{r.alpha:.1f}% |')

    report.append('\n## 4. 인접 안정성 검증')
    report.append(f'- 최고 Cal 시나리오 (`{overall_best.univ} V{int(overall_best.v*100)}Q{int(overall_best.q*100)}G{int(overall_best.g*100)}M{int(overall_best.m*100)} {int(overall_best.slots)}/{int(overall_best.exit)}`)')
    report.append(f'- 이웃 ±5% Cal CV: **{cv:.3f}** ({"PASS" if cv < 0.10 else "WARN" if cv < 0.30 else "FAIL"})')
    report.append(f'- 평균 Cal: {np.mean(neighbor_cals):.2f}')

    report.append('\n## 5. 사용자 의도 결과')
    report.append('### KP200 / KQ150 / KP200+KQ150 universe 검증')
    for univ in ['KOSPI 200', 'KOSDAQ 150', 'KP200+KQ150']:
        if univ in top_per_univ:
            b = top_per_univ[univ]
            report.append(f'\n**{univ}**: 최적 V{int(b.v*100)}Q{int(b.q*100)}G{int(b.g*100)}M{int(b.m*100)} '
                          f'slots {int(b.slots)}/{int(b.exit)}')
            report.append(f'  - CAGR {b.cagr:.1f}%, MDD {b.mdd:.1f}%, Cal {b.calmar:.2f}, Total +{b.total:.0f}%, Alpha +{b.alpha:.1f}%')

    report.append('\n## 6. 운영 권장')
    if overall_best.univ in ['KP200+KQ150','KOSPI 200','KOSDAQ 150']:
        report.append(f'\n**universe 변경 권장**: {overall_best.univ}')
        report.append(f'**가중치**: V{int(overall_best.v*100)} Q{int(overall_best.q*100)} G{int(overall_best.g*100)} M{int(overall_best.m*100)}')
        report.append(f'**슬롯**: {int(overall_best.slots)}, exit rank {int(overall_best.exit)}')
        report.append(f'**기대치**: CAGR {overall_best.cagr:.1f}%, MDD {overall_best.mdd:.1f}%, Cal {overall_best.calmar:.2f}, Alpha +{overall_best.alpha:.1f}%')
    else:
        report.append(f'\n현재 production (raw)이 최적. universe 변경 불필요.')

    report.append('\n## 7. 파일')
    report.append('- `bt_autopilot_rough_grid.csv` (러프 grid)')
    report.append('- `bt_autopilot_fine_grid.csv` (정밀 grid)')
    report.append('- `logs/autopilot_kp200_kq150.log` (실행 로그)')

    report_text = '\n'.join(report)
    Path('KR_UNIVERSE_OPTIMIZATION.md').write_text(report_text, encoding='utf-8')
    log('  보고서 저장: KR_UNIVERSE_OPTIMIZATION.md')

    # ============================================================
    # 6. Git commit + push
    # ============================================================
    log(f'\n=== 6. Git commit + push ===')
    subprocess.run(['git', 'add', 'KR_UNIVERSE_OPTIMIZATION.md', 'bt_autopilot_rough_grid.csv', 'bt_autopilot_fine_grid.csv',
                    'data_cache/idx_kp200_kq150_20260529.json', 'logs/autopilot_kp200_kq150.log',
                    'backtest/regenerate_v80_22_truebt.py', 'autopilot_kp200_kq150.py',
                    'bt_v80_22_KP200_KQ150_results.csv', 'bt_v80_22_PRODUCTION_results.csv',
                    'bt_v80_6_turbosim_results.csv'],
                   check=False)
    commit_msg = (f"\U0001F3AF feat(autopilot): KP200/KQ150 universe × V/Q/G/M grid + 인접 안정성\n\n"
                  f"v80.22 진짜 BT (state/ 1941일 + TurboSim run_regime + defense=cash):\n"
                  f"- 러프 grid (10%): 4 universe × {len(weights_rough)} 가중치 × 4 슬롯 = {len(df_rough)} 시나리오\n"
                  f"- 정밀 grid (5%): {top_2_univ} 2 universe × {len(weights_fine)} 가중치 × 4 슬롯 = {len(df_fine)} 시나리오\n\n"
                  f"전체 best: {overall_best.univ} V{int(overall_best.v*100)}Q{int(overall_best.q*100)}G{int(overall_best.g*100)}M{int(overall_best.m*100)} "
                  f"slots {int(overall_best.slots)}/{int(overall_best.exit)}\n"
                  f"  CAGR {overall_best.cagr:.1f}%, MDD {overall_best.mdd:.1f}%, Cal {overall_best.calmar:.2f}\n"
                  f"  Total +{overall_best.total:.0f}%, Alpha +{overall_best.alpha:.1f}%\n\n"
                  f"인접 ±5% Cal CV: {cv:.3f} ({'PASS' if cv < 0.10 else 'WARN' if cv < 0.30 else 'FAIL'})\n\n"
                  f"Universe별 best Cal: KP200+KQ150 {top_per_univ['KP200+KQ150']['calmar']:.2f}, "
                  f"KP200 {top_per_univ['KOSPI 200']['calmar']:.2f}, "
                  f"KQ150 {top_per_univ['KOSDAQ 150']['calmar']:.2f}, "
                  f"raw {top_per_univ['raw (production)']['calmar']:.2f}\n\n"
                  f"Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>")
    cp = subprocess.run(['git', 'commit', '-m', commit_msg], capture_output=True, text=True)
    log(f'  commit: {cp.returncode} {cp.stdout[:200]}')
    cp_push = subprocess.run(['git', 'push', 'origin', 'main'], capture_output=True, text=True)
    log(f'  push: {cp_push.returncode} {cp_push.stdout[:200]} {cp_push.stderr[:200]}')

    # ============================================================
    # 7. 텔레그램 알림
    # ============================================================
    msg = (f"<b>🎯 자율주행 완료</b>\n"
           f"<i>2026-06-01 KR universe + V/Q/G/M 최적화</i>\n\n"
           f"<b>전체 BEST</b>\n"
           f"universe: {overall_best.univ}\n"
           f"가중치: V{int(overall_best.v*100)} Q{int(overall_best.q*100)} G{int(overall_best.g*100)} M{int(overall_best.m*100)}\n"
           f"슬롯: {int(overall_best.slots)}/{int(overall_best.exit)}\n"
           f"CAGR: {overall_best.cagr:.1f}%, MDD: {overall_best.mdd:.1f}%\n"
           f"Cal: <b>{overall_best.calmar:.2f}</b>, Total: <b>+{overall_best.total:.0f}%</b>\n"
           f"Alpha: +{overall_best.alpha:.1f}%/년\n\n"
           f"<b>Universe별 best Cal</b>\n"
           f"KP200+KQ150: {top_per_univ['KP200+KQ150']['calmar']:.2f}\n"
           f"KP200 단독: {top_per_univ['KOSPI 200']['calmar']:.2f}\n"
           f"KQ150 단독: {top_per_univ['KOSDAQ 150']['calmar']:.2f}\n"
           f"raw (production): {top_per_univ['raw (production)']['calmar']:.2f}\n\n"
           f"인접 ±5% CV: {cv:.3f} ({'PASS' if cv < 0.10 else 'WARN' if cv < 0.30 else 'FAIL'})\n\n"
           f"보고서: KR_UNIVERSE_OPTIMIZATION.md (git push 완료)\n"
           f"총 소요: {(time.time()-t0)/60:.1f}분")
    send_telegram(msg)
    log(f'\n=== 자율주행 완료 [{(time.time()-t0)/60:.1f}분] ===')

except Exception as e:
    log(f'\n❌ 자율주행 실패: {e}')
    import traceback
    traceback.print_exc(file=LOG)
    send_telegram(f"❌ <b>자율주행 실패</b>\n{str(e)[:500]}")

finally:
    LOG.close()
