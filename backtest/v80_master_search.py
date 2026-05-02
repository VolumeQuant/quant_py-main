"""v80 마스터 탐색 — 파라미터 의존관계 반영, 단계별 인사이트 → 다음 단계 설계

Phase 5a 오류 방지:
  - Tier 1에서 G서브 + VQGM + 모멘텀 동시 탐색
  - Tier 2(E/X/S) 확정 후 Tier 1 Top 10 재확인 (최종 조건 재확인 원칙)
  - 양쪽 BT(7.8y + 5.25y) 동시 통과 필수
  - WF 4구간 + 인접안정성 + CV 검증

탐색 순서:
  Phase 1a: Coarse VQGM × G타입(2f/3f 대표) × 모멘텀 (러프)
  Phase 1b: Fine G서브 가중치 (Phase 1a 유망 영역)
  Phase 1c: E/X/S (Phase 1a+1b Top 10)
  Phase 1d: 최종 조건 재확인 + 인접안정성
  Phase 2:  방어 모드 탐색
  Phase 3:  국면 판단 (MA기간 × 확인일)
  Phase 4:  교차검증 (공격Top × 방어Top × 국면Top, WF+인접)
"""
import sys, os, json, glob, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, 'backtest')
sys.path.insert(0, '.')

import pandas as pd, numpy as np
import requests
from pathlib import Path
from itertools import product
from turbo_simulator import TurboSimulator

# ── 텔레그램 ──
from config import TELEGRAM_BOT_TOKEN as BOT_TOKEN, TELEGRAM_PRIVATE_ID as PRIVATE_ID
def send_tg(msg):
    try:
        requests.post(f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
                      data={'chat_id': PRIVATE_ID, 'text': msg, 'parse_mode': 'HTML'}, timeout=30)
    except: pass

# ── 데이터 로드 (1회, 캐시 재사용) ──
print('=== 데이터 로드 ===', flush=True)
t_start = time.time()

def load_rankings(dirs):
    data = {}
    for d in dirs:
        d = Path(d)
        if not d.exists(): continue
        for fp in sorted(d.glob('ranking_*.json')):
            k = fp.stem.replace('ranking_', '')
            if len(k) != 8: continue
            if k not in data:
                with open(fp, 'r', encoding='utf-8') as f:
                    data[k] = json.load(f)
    return data

boost_rd = load_rankings(['backtest/bt_extended', 'state'])
defense_rd = load_rankings(['backtest/bt_extended_defense', 'state/defense'])
all_dates = sorted(set(boost_rd) & set(defense_rd))
boost_rk = {d: boost_rd[d]['rankings'] for d in all_dates}
print(f'  ranking: {len(all_dates)}일', flush=True)

ohlcv = pd.read_parquet(sorted(glob.glob('data_cache/all_ohlcv_2017*.parquet'))[-1]).replace(0, np.nan)
kdf = pd.read_parquet('data_cache/kospi_yf.parquet')
kospi = kdf.iloc[:, 0].fillna(kdf['kospi']).sort_index()

# MA 사전 계산 (Phase 3용 — 여러 기간)
MA_CACHE = {}
for period in [100, 150, 200, 250]:
    MA_CACHE[period] = kospi.rolling(period).mean()

def calc_regime(target_dates, ma_period=200, confirm=7):
    ma = MA_CACHE[ma_period]
    reg = {}; md = False; stk = 0; ss = None
    for d in target_dates:
        ts = pd.Timestamp(d); kv = kospi.get(ts); mv = ma.get(ts)
        if kv is None or pd.isna(mv): reg[d] = md; continue
        s = kv > mv
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= confirm and md != s: md = s
        reg[d] = md
    return reg

# BT 기간 정의
PERIODS = {
    '7.8y':      ('20180702', '20260414'),
    '5.25y':     ('20210104', '20260414'),
}
WF_PERIODS = {
    '2018H2-19': ('20180702', '20191231'),
    '2020-21':   ('20200102', '20211230'),
    '2022-23':   ('20220103', '20231228'),
    '2024-26':   ('20240102', '20260414'),
}

# TurboSimulator 사전 초기화 (기간별 1회, 재사용)
print('  TurboSimulator 초기화...', flush=True)
TSIMS = {}
for pname, (ps, pe) in {**PERIODS, **WF_PERIODS}.items():
    pd_ = [d for d in all_dates if ps <= d <= pe]
    if len(pd_) >= 50:
        TSIMS[pname] = (pd_, TurboSimulator({d: boost_rk[d] for d in pd_}, pd_, ohlcv))

# v79 기본 국면 (Phase 3 전까지 고정)
DEFAULT_REGIME = {pname: calc_regime(pd_, 200, 7) for pname, (pd_, _) in TSIMS.items()}

print(f'  초기화 완료: {time.time()-t_start:.1f}초\n', flush=True)


def run_bt(offense, defense, gs_o, gs_d, regime_dict_map, periods=None, trailing=-0.15):
    """주어진 파라미터로 BT 실행. {period: {cal, cagr, mdd}} 반환"""
    if periods is None:
        periods = ['7.8y', '5.25y']
    results = {}
    for pname in periods:
        if pname not in TSIMS: continue
        pd_, tsim = TSIMS[pname]
        reg = regime_dict_map.get(pname, DEFAULT_REGIME.get(pname, {}))
        try:
            r = tsim.run_regime(
                defense_params=defense, offense_params=offense,
                regime_dict=reg, trailing_stop=trailing,
                g_sub1_o=gs_o[0], g_sub2_o=gs_o[1], g_sub3_o=gs_o[2],
                g_w1_o=gs_o[3], g_w2_o=gs_o[4], g_w3_o=gs_o[5],
                g_sub1_d=gs_d[0], g_sub2_d=gs_d[1], g_sub3_d=gs_d[2],
                g_w1_d=gs_d[3], g_w2_d=gs_d[4], g_w3_d=gs_d[5],
            )
            results[pname] = {'cal': r['calmar'], 'cagr': r['cagr'], 'mdd': r['mdd']}
        except Exception:
            results[pname] = {'cal': 0, 'cagr': 0, 'mdd': 0}
    return results


def score_combo(results):
    """7.8y + 5.25y 양쪽 Cal 기하평균 (양쪽 통과 원칙)"""
    c78 = results.get('7.8y', {}).get('cal', 0)
    c525 = results.get('5.25y', {}).get('cal', 0)
    if c78 <= 0 or c525 <= 0:
        return 0
    return (c78 * c525) ** 0.5  # 기하평균


# ═══════════════════════════════════════════════════════════
# Phase 1a: Coarse VQGM × G타입 × 모멘텀 (러프 탐색)
# ═══════════════════════════════════════════════════════════
print('=' * 60)
print('Phase 1a: Coarse VQGM × G타입 × 모멘텀')
print('=' * 60, flush=True)

# 방어 모드 고정 (Phase 2에서 탐색)
DEF_FIXED = {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,'entry':3,'exit':6,'slots':7,'mom':'6m-1m'}
GS_D_FIXED = ('rev_z','oca_z',None,None,None,None)

# 탐색 범위 (역대 v67~v79 인사이트 반영)
VW = [0, 5, 10, 15, 20, 25, 30]
QW = [0, 5, 10, 15]
GW = [20, 25, 30, 35, 40, 45, 50, 55, 60, 65]
MW = [15, 20, 25, 30, 35, 40, 45]
MOMS = ['6m', '6m-1m', '12m', '12m-1m']

# G서브 대표 (2f vs 3f 핵심 비교)
G_SUBS_COARSE = [
    ('2f_rev_oca_60', 'rev_z','oca_z',None, 0.6, None,None,None),
    ('2f_rev_oca_70', 'rev_z','oca_z',None, 0.7, None,None,None),
    ('3f_rev_oca_gp', 'rev_z','oca_z','gp_growth_z', None, 0.5,0.3,0.2),
    ('3f_rev_oca_opm', 'rev_z','oca_z','op_margin_z', None, 0.5,0.3,0.2),
]

# 유효 VQGM 조합 생성
vqgm_combos = [(v,q,g,m) for v,q,g,m in product(VW,QW,GW,MW) if v+q+g+m == 100]
print(f'  VQGM 유효: {len(vqgm_combos)}조합')
total_1a = len(vqgm_combos) * len(MOMS) * len(G_SUBS_COARSE)
print(f'  총 조합: {total_1a} (VQGM {len(vqgm_combos)} × MOM {len(MOMS)} × GS {len(G_SUBS_COARSE)})')
print(f'  E/X/S 고정: E3X6S3 (v79)\n', flush=True)

# 표본 10건 먼저
print('  [표본 10건]', flush=True)
sample_count = 0
for v,q,g,m in vqgm_combos[:3]:
    for mom in MOMS[:2]:
        for gs_label, s1, s2, s3, g_rev, w1, w2, w3 in G_SUBS_COARSE[:2]:
            offense = {'v':v/100,'q':q/100,'g':g/100,'m':m/100,
                       'g_rev': g_rev if g_rev else (w1 or 0.5),
                       'entry':3,'exit':6,'slots':3,'mom':mom}
            gs_o = (s1, s2, s3, w1, w2, w3)
            r = run_bt(offense, DEF_FIXED, gs_o, GS_D_FIXED, DEFAULT_REGIME)
            c78 = r.get('7.8y',{}).get('cal',0)
            c525 = r.get('5.25y',{}).get('cal',0)
            print(f'    V{v}Q{q}G{g}M{m} {mom} {gs_label}: 7.8y={c78:.2f} 5.25y={c525:.2f}', flush=True)
            sample_count += 1
            if sample_count >= 10:
                break
        if sample_count >= 10: break
    if sample_count >= 10: break
print('  표본 OK\n', flush=True)

# 전체 실행
results_1a = []
t0 = time.time()
count = 0
for v,q,g,m in vqgm_combos:
    for mom in MOMS:
        for gs_label, s1, s2, s3, g_rev, w1, w2, w3 in G_SUBS_COARSE:
            offense = {'v':v/100,'q':q/100,'g':g/100,'m':m/100,
                       'g_rev': g_rev if g_rev else (w1 or 0.5),
                       'entry':3,'exit':6,'slots':3,'mom':mom}
            gs_o = (s1, s2, s3, w1, w2, w3)
            r = run_bt(offense, DEF_FIXED, gs_o, GS_D_FIXED, DEFAULT_REGIME)
            sc = score_combo(r)
            results_1a.append({
                'V':v, 'Q':q, 'G':g, 'M':m, 'mom':mom, 'gs':gs_label,
                'cal_78': r.get('7.8y',{}).get('cal',0),
                'cagr_78': r.get('7.8y',{}).get('cagr',0),
                'mdd_78': r.get('7.8y',{}).get('mdd',0),
                'cal_525': r.get('5.25y',{}).get('cal',0),
                'cagr_525': r.get('5.25y',{}).get('cagr',0),
                'mdd_525': r.get('5.25y',{}).get('mdd',0),
                'score': sc,
            })
            count += 1
            if count % 200 == 0:
                elapsed = time.time() - t0
                eta = (total_1a - count) / (count / elapsed) if count > 0 else 0
                print(f'  [{count}/{total_1a}] {elapsed:.0f}s (ETA {eta:.0f}s)', flush=True)

elapsed_1a = time.time() - t0
df_1a = pd.DataFrame(results_1a).sort_values('score', ascending=False)
df_1a.to_csv('backtest/v80_phase1a_coarse.csv', index=False, encoding='utf-8-sig')
print(f'\n  Phase 1a 완료: {len(df_1a)}조합, {elapsed_1a:.0f}초', flush=True)

# Phase 1a EDA
print(f'\n  === Phase 1a Top 15 (기하평균 기준) ===')
for i, (_, r) in enumerate(df_1a.head(15).iterrows()):
    marker = ' ←v79' if r['V']==15 and r['Q']==5 and r['G']==50 and r['M']==30 and r['gs']=='3f_rev_oca_gp' and r['mom']=='12m' else ''
    print(f'  {i+1:>3}. V{r["V"]}Q{r["Q"]}G{r["G"]}M{r["M"]} {r["mom"]:>6} {r["gs"]:>18}: '
          f'7.8y={r["cal_78"]:.2f} 5.25y={r["cal_525"]:.2f} score={r["score"]:.3f}{marker}', flush=True)

# v79 순위 확인
v79_mask = (df_1a['V']==15) & (df_1a['Q']==5) & (df_1a['G']==50) & (df_1a['M']==30) & (df_1a['gs']=='3f_rev_oca_gp') & (df_1a['mom']=='12m')
v79_row = df_1a[v79_mask]
if not v79_row.empty:
    v79_rank = (df_1a['score'] > v79_row.iloc[0]['score']).sum() + 1
    print(f'\n  v79 현재: {v79_rank}위/{len(df_1a)} (score={v79_row.iloc[0]["score"]:.3f})')

# 2f vs 3f 비교
print(f'\n  2f vs 3f Top 10:')
for gs_prefix in ['2f', '3f']:
    sub = df_1a[df_1a['gs'].str.startswith(gs_prefix)].head(5)
    print(f'    {gs_prefix} Top 5 score: {sub["score"].values[:5].round(3).tolist()}')

# 유망 영역 식별
top30 = df_1a.head(30)
print(f'\n  Top 30 VQGM 분포:')
print(f'    V: {sorted(top30["V"].unique())}')
print(f'    Q: {sorted(top30["Q"].unique())}')
print(f'    G: {sorted(top30["G"].unique())}')
print(f'    M: {sorted(top30["M"].unique())}')
print(f'    MOM: {top30["mom"].value_counts().to_dict()}')
print(f'    GS: {top30["gs"].value_counts().to_dict()}')

# 텔레그램 1a 결과
top5_str = '\n'.join([
    f'{i+1}. V{r["V"]}Q{r["Q"]}G{r["G"]}M{r["M"]} {r["mom"]} {r["gs"]}: '
    f'7.8y={r["cal_78"]:.2f} 5.25y={r["cal_525"]:.2f}'
    for i, (_, r) in enumerate(df_1a.head(5).iterrows())
])
v79_info = f'v79 순위: {v79_rank}위/{len(df_1a)}' if not v79_row.empty else 'v79 미발견'
send_tg(f'<b>[v80 Phase 1a] Coarse 탐색 완료</b>\n\n'
        f'{len(df_1a)}조합 탐색 ({elapsed_1a:.0f}초)\n\n'
        f'<b>Top 5:</b>\n<pre>{top5_str}</pre>\n\n'
        f'{v79_info}\n\n'
        f'Top 30 GS 분포: {top30["gs"].value_counts().to_dict()}\n'
        f'Top 30 MOM 분포: {top30["mom"].value_counts().to_dict()}')


# ═══════════════════════════════════════════════════════════
# Phase 1b: Fine G서브 가중치 (Phase 1a 유망 영역)
# ═══════════════════════════════════════════════════════════
print(f'\n{"="*60}')
print('Phase 1b: Fine G서브 가중치')
print(f'{"="*60}', flush=True)

# Phase 1a Top 10의 VQGM+MOM 조합에서 G서브 가중치 세밀 탐색
top10_configs = df_1a.head(10)[['V','Q','G','M','mom']].drop_duplicates().values.tolist()
print(f'  Top 10 VQGM+MOM 유니크: {len(top10_configs)}조합')

G_SUBS_FINE = [
    # 2팩터 세밀
    ('2f_50', 'rev_z','oca_z',None, 0.50, None,None,None),
    ('2f_55', 'rev_z','oca_z',None, 0.55, None,None,None),
    ('2f_60', 'rev_z','oca_z',None, 0.60, None,None,None),
    ('2f_65', 'rev_z','oca_z',None, 0.65, None,None,None),
    ('2f_70', 'rev_z','oca_z',None, 0.70, None,None,None),
    ('2f_75', 'rev_z','oca_z',None, 0.75, None,None,None),
    ('2f_80', 'rev_z','oca_z',None, 0.80, None,None,None),
    # 3팩터 세밀 (rev+oca+gp)
    ('3f_gp_532', 'rev_z','oca_z','gp_growth_z', None, 0.5,0.3,0.2),
    ('3f_gp_433', 'rev_z','oca_z','gp_growth_z', None, 0.4,0.3,0.3),
    ('3f_gp_622', 'rev_z','oca_z','gp_growth_z', None, 0.6,0.2,0.2),
    ('3f_gp_442', 'rev_z','oca_z','gp_growth_z', None, 0.4,0.4,0.2),
    # 3팩터 (rev+oca+opm)
    ('3f_opm_532', 'rev_z','oca_z','op_margin_z', None, 0.5,0.3,0.2),
    ('3f_opm_622', 'rev_z','oca_z','op_margin_z', None, 0.6,0.2,0.2),
    # 3팩터 (rev+oca+accel)
    ('3f_acc_532', 'rev_z','oca_z','rev_accel_z', None, 0.5,0.3,0.2),
    ('3f_acc_622', 'rev_z','oca_z','rev_accel_z', None, 0.6,0.2,0.2),
]

results_1b = []
t0 = time.time()
total_1b = len(top10_configs) * len(G_SUBS_FINE)
count = 0

for v, q, g, m, mom in top10_configs:
    for gs_label, s1, s2, s3, g_rev, w1, w2, w3 in G_SUBS_FINE:
        offense = {'v':v/100,'q':q/100,'g':g/100,'m':m/100,
                   'g_rev': g_rev if g_rev else (w1 or 0.5),
                   'entry':3,'exit':6,'slots':3,'mom':mom}
        gs_o = (s1, s2, s3, w1, w2, w3)
        r = run_bt(offense, DEF_FIXED, gs_o, GS_D_FIXED, DEFAULT_REGIME)
        sc = score_combo(r)
        results_1b.append({
            'V':v, 'Q':q, 'G':g, 'M':m, 'mom':mom, 'gs':gs_label,
            'cal_78': r.get('7.8y',{}).get('cal',0),
            'cal_525': r.get('5.25y',{}).get('cal',0),
            'score': sc,
        })
        count += 1
        if count % 50 == 0:
            print(f'  [{count}/{total_1b}] {time.time()-t0:.0f}s', flush=True)

df_1b = pd.DataFrame(results_1b).sort_values('score', ascending=False)
df_1b.to_csv('backtest/v80_phase1b_fine_gsub.csv', index=False, encoding='utf-8-sig')
print(f'\n  Phase 1b 완료: {len(df_1b)}조합, {time.time()-t0:.0f}초')

print(f'\n  === Phase 1b Top 10 ===')
for i, (_, r) in enumerate(df_1b.head(10).iterrows()):
    print(f'  {i+1:>3}. V{r["V"]}Q{r["Q"]}G{r["G"]}M{r["M"]} {r["mom"]:>6} {r["gs"]:>15}: '
          f'7.8y={r["cal_78"]:.2f} 5.25y={r["cal_525"]:.2f} score={r["score"]:.3f}', flush=True)

# 1a+1b 통합 Top 20
df_combined = pd.concat([df_1a, df_1b]).sort_values('score', ascending=False).drop_duplicates(
    subset=['V','Q','G','M','mom','gs'], keep='first').head(20)
print(f'\n  === 1a+1b 통합 Top 20 ===')
for i, (_, r) in enumerate(df_combined.head(20).iterrows()):
    print(f'  {i+1:>3}. V{r["V"]}Q{r["Q"]}G{r["G"]}M{r["M"]} {r["mom"]:>6} {r["gs"]:>18}: score={r["score"]:.3f}', flush=True)

send_tg(f'<b>[v80 Phase 1b] Fine G서브 완료</b>\n\n'
        f'Top 1: V{df_1b.iloc[0]["V"]}Q{df_1b.iloc[0]["Q"]}G{df_1b.iloc[0]["G"]}M{df_1b.iloc[0]["M"]} '
        f'{df_1b.iloc[0]["mom"]} {df_1b.iloc[0]["gs"]} score={df_1b.iloc[0]["score"]:.3f}')


# ═══════════════════════════════════════════════════════════
# Phase 1c: E/X/S 탐색 (통합 Top 10)
# ═══════════════════════════════════════════════════════════
print(f'\n{"="*60}')
print('Phase 1c: E/X/S 탐색')
print(f'{"="*60}', flush=True)

EXS_RANGE = [(e,x,s) for e in [3,5,7] for x in [6,8,10] for s in [3,5,7]
             if x > e and s <= 7]  # x > e 제약

top10_for_exs = df_combined.head(10)
results_1c = []
t0 = time.time()
total_1c = len(top10_for_exs) * len(EXS_RANGE)
count = 0

for _, cfg in top10_for_exs.iterrows():
    v,q,g,m,mom,gs_label = int(cfg['V']),int(cfg['Q']),int(cfg['G']),int(cfg['M']),cfg['mom'],cfg['gs']
    # G서브 파라미터 복원
    gs_map = {gs[0]: gs for gs in G_SUBS_COARSE + G_SUBS_FINE}
    if gs_label in gs_map:
        _, s1, s2, s3, g_rev, w1, w2, w3 = gs_map[gs_label]
    else:
        continue

    for e, x, s in EXS_RANGE:
        offense = {'v':v/100,'q':q/100,'g':g/100,'m':m/100,
                   'g_rev': g_rev if g_rev else (w1 or 0.5),
                   'entry':e,'exit':x,'slots':s,'mom':mom}
        gs_o = (s1, s2, s3, w1, w2, w3)
        r = run_bt(offense, DEF_FIXED, gs_o, GS_D_FIXED, DEFAULT_REGIME)
        sc = score_combo(r)
        results_1c.append({
            'V':v,'Q':q,'G':g,'M':m,'mom':mom,'gs':gs_label,
            'E':e,'X':x,'S':s,
            'cal_78': r.get('7.8y',{}).get('cal',0),
            'cal_525': r.get('5.25y',{}).get('cal',0),
            'score': sc,
        })
        count += 1
        if count % 50 == 0:
            print(f'  [{count}/{total_1c}] {time.time()-t0:.0f}s', flush=True)

df_1c = pd.DataFrame(results_1c).sort_values('score', ascending=False)
df_1c.to_csv('backtest/v80_phase1c_exs.csv', index=False, encoding='utf-8-sig')
print(f'\n  Phase 1c 완료: {len(df_1c)}조합, {time.time()-t0:.0f}초')

print(f'\n  === Phase 1c Top 10 ===')
for i, (_, r) in enumerate(df_1c.head(10).iterrows()):
    print(f'  {i+1:>3}. V{r["V"]}Q{r["Q"]}G{r["G"]}M{r["M"]} {r["mom"]:>6} {r["gs"]:>15} E{r["E"]}X{r["X"]}S{r["S"]}: '
          f'7.8y={r["cal_78"]:.2f} 5.25y={r["cal_525"]:.2f} score={r["score"]:.3f}', flush=True)

# ★ 최종 조건 재확인: Phase 1c Top E/X/S로 Phase 1a+1b의 모든 Top 20 재평가
print(f'\n  [최종 조건 재확인] Top E/X/S로 1a+1b Top 20 재검증')
best_exs = (int(df_1c.iloc[0]['E']), int(df_1c.iloc[0]['X']), int(df_1c.iloc[0]['S']))
print(f'  Best E/X/S: E{best_exs[0]}X{best_exs[1]}S{best_exs[2]}')

recheck_results = []
for _, cfg in df_combined.head(20).iterrows():
    v,q,g,m,mom,gs_label = int(cfg['V']),int(cfg['Q']),int(cfg['G']),int(cfg['M']),cfg['mom'],cfg['gs']
    if gs_label in gs_map:
        _, s1, s2, s3, g_rev, w1, w2, w3 = gs_map[gs_label]
    else: continue
    offense = {'v':v/100,'q':q/100,'g':g/100,'m':m/100,
               'g_rev': g_rev if g_rev else (w1 or 0.5),
               'entry':best_exs[0],'exit':best_exs[1],'slots':best_exs[2],'mom':mom}
    gs_o = (s1, s2, s3, w1, w2, w3)
    r = run_bt(offense, DEF_FIXED, gs_o, GS_D_FIXED, DEFAULT_REGIME)
    sc = score_combo(r)
    recheck_results.append({
        'V':v,'Q':q,'G':g,'M':m,'mom':mom,'gs':gs_label,
        'E':best_exs[0],'X':best_exs[1],'S':best_exs[2],
        'cal_78': r.get('7.8y',{}).get('cal',0),
        'cal_525': r.get('5.25y',{}).get('cal',0),
        'score': sc,
    })

df_recheck = pd.DataFrame(recheck_results).sort_values('score', ascending=False)
print(f'\n  === 재확인 Top 10 (Best E/X/S 적용) ===')
for i, (_, r) in enumerate(df_recheck.head(10).iterrows()):
    print(f'  {i+1:>3}. V{r["V"]}Q{r["Q"]}G{r["G"]}M{r["M"]} {r["mom"]:>6} {r["gs"]:>15}: '
          f'7.8y={r["cal_78"]:.2f} 5.25y={r["cal_525"]:.2f} score={r["score"]:.3f}', flush=True)

send_tg(f'<b>[v80 Phase 1c] E/X/S + 재확인 완료</b>\n\n'
        f'Best E/X/S: E{best_exs[0]}X{best_exs[1]}S{best_exs[2]}\n'
        f'재확인 Top 1: V{df_recheck.iloc[0]["V"]}Q{df_recheck.iloc[0]["Q"]}G{df_recheck.iloc[0]["G"]}M{df_recheck.iloc[0]["M"]} '
        f'{df_recheck.iloc[0]["mom"]} {df_recheck.iloc[0]["gs"]} score={df_recheck.iloc[0]["score"]:.3f}')


# ═══════════════════════════════════════════════════════════
# Phase 1d: 인접안정성 (Top 10)
# ═══════════════════════════════════════════════════════════
print(f'\n{"="*60}')
print('Phase 1d: 인접안정성 (Top 10)')
print(f'{"="*60}', flush=True)

top10_final = df_recheck.head(10)
stability_results = []

for idx, (_, cfg) in enumerate(top10_final.iterrows()):
    v,q,g,m = int(cfg['V']),int(cfg['Q']),int(cfg['G']),int(cfg['M'])
    mom, gs_label = cfg['mom'], cfg['gs']
    base_score = cfg['score']

    # V,Q,G,M 각각 ±5 변동 (합=100 유지)
    neighbors = []
    for param, delta in [('V',5),('V',-5),('Q',5),('Q',-5),('G',5),('G',-5),('M',5),('M',-5)]:
        nv,nq,ng,nm = v,q,g,m
        if param=='V': nv += delta; nm -= delta
        elif param=='Q': nq += delta; nm -= delta
        elif param=='G': ng += delta; nm -= delta
        elif param=='M': nm += delta; ng -= delta  # M변경시 G에서 차감
        if all(x >= 0 for x in [nv,nq,ng,nm]) and nv+nq+ng+nm == 100:
            neighbors.append((nv,nq,ng,nm))

    neighbor_scores = []
    for nv,nq,ng,nm in neighbors:
        if gs_label in gs_map:
            _, s1, s2, s3, g_rev, w1, w2, w3 = gs_map[gs_label]
        else: continue
        offense = {'v':nv/100,'q':nq/100,'g':ng/100,'m':nm/100,
                   'g_rev': g_rev if g_rev else (w1 or 0.5),
                   'entry':best_exs[0],'exit':best_exs[1],'slots':best_exs[2],'mom':mom}
        gs_o = (s1, s2, s3, w1, w2, w3)
        r = run_bt(offense, DEF_FIXED, gs_o, GS_D_FIXED, DEFAULT_REGIME)
        neighbor_scores.append(score_combo(r))

    if neighbor_scores:
        adj_mean = sum(neighbor_scores) / len(neighbor_scores)
        adj_min = min(neighbor_scores)
        adj_cv = (pd.Series(neighbor_scores).std() / adj_mean) if adj_mean > 0 else 999
    else:
        adj_mean = adj_min = adj_cv = 0

    stability_results.append({
        'rank': idx+1, 'V':v,'Q':q,'G':g,'M':m,'mom':mom,'gs':gs_label,
        'base_score': base_score, 'adj_mean': adj_mean, 'adj_min': adj_min, 'adj_cv': adj_cv,
    })
    print(f'  #{idx+1} V{v}Q{q}G{g}M{m} {mom} {gs_label}: '
          f'base={base_score:.3f} adj_mean={adj_mean:.3f} adj_min={adj_min:.3f} CV={adj_cv:.2f}', flush=True)

df_stability = pd.DataFrame(stability_results)
print(f'\n  인접안정성 CV < 0.3 통과:')
for _, r in df_stability.iterrows():
    status = 'PASS' if r['adj_cv'] < 0.3 else 'FAIL'
    print(f'    #{r["rank"]} CV={r["adj_cv"]:.2f} {status}')

# 공격 Top 5 확정
attack_top5 = df_stability[df_stability['adj_cv'] < 0.3].head(5)
if len(attack_top5) < 3:
    attack_top5 = df_stability.head(5)  # CV 필터 너무 엄격하면 완화
print(f'\n  공격 모드 Top 5 확정: {len(attack_top5)}개')

send_tg(f'<b>[v80 Phase 1d] 공격 모드 인접안정성 완료</b>\n\n'
        f'Top 5 (CV<0.3 통과):\n' +
        '\n'.join([f'{i+1}. V{r["V"]}Q{r["Q"]}G{r["G"]}M{r["M"]} {r["mom"]} {r["gs"]} '
                   f'score={r["base_score"]:.3f} CV={r["adj_cv"]:.2f}'
                   for i, (_, r) in enumerate(attack_top5.iterrows())]))


# ═══════════════════════════════════════════════════════════
# Phase 2: 방어 모드 탐색
# ═══════════════════════════════════════════════════════════
print(f'\n{"="*60}')
print('Phase 2: 방어 모드 탐색')
print(f'{"="*60}', flush=True)

# 공격 Top 1 고정, 방어 파라미터 탐색
atk_best = attack_top5.iloc[0]
atk_v,atk_q,atk_g,atk_m = int(atk_best['V']),int(atk_best['Q']),int(atk_best['G']),int(atk_best['M'])
atk_mom, atk_gs = atk_best['mom'], atk_best['gs']
_, s1o, s2o, s3o, g_rev_o, w1o, w2o, w3o = gs_map[atk_gs]
ATK_OFFENSE = {'v':atk_v/100,'q':atk_q/100,'g':atk_g/100,'m':atk_m/100,
               'g_rev': g_rev_o if g_rev_o else (w1o or 0.5),
               'entry':best_exs[0],'exit':best_exs[1],'slots':best_exs[2],'mom':atk_mom}
ATK_GS_O = (s1o, s2o, s3o, w1o, w2o, w3o)

# 방어 탐색 범위
DEF_VW = [20, 25, 30, 35, 40]
DEF_QW = [0, 5, 10, 15, 20]
DEF_GW = [5, 10, 15, 20, 25]
DEF_MW = [30, 35, 40, 45, 50, 55]
DEF_MOMS = ['6m', '6m-1m']
DEF_GS = [
    ('2f_60', 'rev_z','oca_z',None, 0.6, None,None,None),
    ('2f_70', 'rev_z','oca_z',None, 0.7, None,None,None),
    ('2f_80', 'rev_z','oca_z',None, 0.8, None,None,None),
]
DEF_EXS = [(3,6,5), (3,6,7), (3,8,7), (5,8,7), (5,10,7)]

def_combos = [(v,q,g,m) for v,q,g,m in product(DEF_VW,DEF_QW,DEF_GW,DEF_MW) if v+q+g+m==100]
total_2 = len(def_combos) * len(DEF_MOMS) * len(DEF_GS) * len(DEF_EXS)
print(f'  방어 VQGM: {len(def_combos)}, 총 조합: {total_2}', flush=True)

results_2 = []
t0 = time.time()
count = 0
for v,q,g,m in def_combos:
    for mom in DEF_MOMS:
        for gs_label, s1d, s2d, s3d, g_rev_d, w1d, w2d, w3d in DEF_GS:
            for e,x,s in DEF_EXS:
                defense = {'v':v/100,'q':q/100,'g':g/100,'m':m/100,
                           'g_rev': g_rev_d or 0.7,
                           'entry':e,'exit':x,'slots':s,'mom':mom}
                gs_d = (s1d, s2d, s3d, w1d, w2d, w3d)
                r = run_bt(ATK_OFFENSE, defense, ATK_GS_O, gs_d, DEFAULT_REGIME)
                sc = score_combo(r)
                results_2.append({
                    'dV':v,'dQ':q,'dG':g,'dM':m,'d_mom':mom,'d_gs':gs_label,
                    'dE':e,'dX':x,'dS':s,
                    'cal_78': r.get('7.8y',{}).get('cal',0),
                    'cal_525': r.get('5.25y',{}).get('cal',0),
                    'score': sc,
                })
                count += 1
                if count % 200 == 0:
                    print(f'  [{count}/{total_2}] {time.time()-t0:.0f}s', flush=True)

df_2 = pd.DataFrame(results_2).sort_values('score', ascending=False)
df_2.to_csv('backtest/v80_phase2_defense.csv', index=False, encoding='utf-8-sig')
print(f'\n  Phase 2 완료: {len(df_2)}조합, {time.time()-t0:.0f}초')

print(f'\n  === Phase 2 방어 Top 5 ===')
for i, (_, r) in enumerate(df_2.head(5).iterrows()):
    print(f'  {i+1}. V{r["dV"]}Q{r["dQ"]}G{r["dG"]}M{r["dM"]} {r["d_mom"]} {r["d_gs"]} '
          f'E{r["dE"]}X{r["dX"]}S{r["dS"]}: score={r["score"]:.3f}', flush=True)

send_tg(f'<b>[v80 Phase 2] 방어 모드 완료</b>\n\n'
        f'Top 1: V{df_2.iloc[0]["dV"]}Q{df_2.iloc[0]["dQ"]}G{df_2.iloc[0]["dG"]}M{df_2.iloc[0]["dM"]} '
        f'{df_2.iloc[0]["d_mom"]} E{df_2.iloc[0]["dE"]}X{df_2.iloc[0]["dX"]}S{df_2.iloc[0]["dS"]} '
        f'score={df_2.iloc[0]["score"]:.3f}')


# ═══════════════════════════════════════════════════════════
# Phase 3: 국면 판단 (MA기간 × 확인일)
# ═══════════════════════════════════════════════════════════
print(f'\n{"="*60}')
print('Phase 3: 국면 판단 탐색')
print(f'{"="*60}', flush=True)

# 공격 Top 1 + 방어 Top 1 고정
def_best = df_2.iloc[0]
DEF_BEST = {'v':def_best['dV']/100,'q':def_best['dQ']/100,'g':def_best['dG']/100,'m':def_best['dM']/100,
            'g_rev':0.7, 'entry':int(def_best['dE']),'exit':int(def_best['dX']),'slots':int(def_best['dS']),
            'mom':def_best['d_mom']}
_, s1db, s2db, s3db, g_rev_db, w1db, w2db, w3db = gs_map.get(def_best['d_gs'], gs_map.get('2f_rev_oca_70'))
GS_D_BEST = (s1db, s2db, s3db, w1db, w2db, w3db)

MA_PERIODS = [100, 150, 200, 250]
CONFIRM_DAYS = [3, 5, 7, 10, 15]

results_3 = []
for ma_p in MA_PERIODS:
    for cd in CONFIRM_DAYS:
        regime_map = {}
        for pname, (pd_, _) in TSIMS.items():
            regime_map[pname] = calc_regime(pd_, ma_p, cd)
        r = run_bt(ATK_OFFENSE, DEF_BEST, ATK_GS_O, GS_D_BEST, regime_map)
        sc = score_combo(r)
        results_3.append({
            'ma': ma_p, 'confirm': cd,
            'cal_78': r.get('7.8y',{}).get('cal',0),
            'cal_525': r.get('5.25y',{}).get('cal',0),
            'score': sc,
        })
        print(f'  MA{ma_p} {cd}d: 7.8y={r.get("7.8y",{}).get("cal",0):.2f} '
              f'5.25y={r.get("5.25y",{}).get("cal",0):.2f} score={sc:.3f}', flush=True)

df_3 = pd.DataFrame(results_3).sort_values('score', ascending=False)
print(f'\n  === 국면 Top 5 ===')
for i, (_, r) in enumerate(df_3.head(5).iterrows()):
    print(f'  {i+1}. MA{r["ma"]} {r["confirm"]}d: score={r["score"]:.3f}')

send_tg(f'<b>[v80 Phase 3] 국면 판단 완료</b>\n\n'
        f'Top 1: MA{df_3.iloc[0]["ma"]} {df_3.iloc[0]["confirm"]}d score={df_3.iloc[0]["score"]:.3f}\n'
        f'v79(MA200 7d) 비교: {df_3[(df_3["ma"]==200)&(df_3["confirm"]==7)].iloc[0]["score"]:.3f}' if len(df_3[(df_3["ma"]==200)&(df_3["confirm"]==7)]) > 0 else '')


# ═══════════════════════════════════════════════════════════
# Phase 4: 교차 검증 + WF (Top 5 공격 × Top 3 방어 × Top 3 국면)
# ═══════════════════════════════════════════════════════════
print(f'\n{"="*60}')
print('Phase 4: 교차 검증 + WF')
print(f'{"="*60}', flush=True)

atk_top5_list = attack_top5.head(5)
def_top3 = df_2.head(3)
regime_top3 = df_3.head(3)

results_4 = []
for _, atk in atk_top5_list.iterrows():
    av,aq,ag,am = int(atk['V']),int(atk['Q']),int(atk['G']),int(atk['M'])
    a_mom, a_gs = atk['mom'], atk['gs']
    _, s1a, s2a, s3a, gr_a, w1a, w2a, w3a = gs_map[a_gs]
    a_off = {'v':av/100,'q':aq/100,'g':ag/100,'m':am/100,
             'g_rev': gr_a if gr_a else (w1a or 0.5),
             'entry':best_exs[0],'exit':best_exs[1],'slots':best_exs[2],'mom':a_mom}
    a_gs_o = (s1a, s2a, s3a, w1a, w2a, w3a)

    for _, d in def_top3.iterrows():
        d_def = {'v':d['dV']/100,'q':d['dQ']/100,'g':d['dG']/100,'m':d['dM']/100,
                 'g_rev':0.7, 'entry':int(d['dE']),'exit':int(d['dX']),'slots':int(d['dS']),
                 'mom':d['d_mom']}
        _, s1d, s2d, s3d, grd, w1d, w2d, w3d = gs_map.get(d['d_gs'], gs_map.get('2f_rev_oca_70'))
        d_gs_d = (s1d, s2d, s3d, w1d, w2d, w3d)

        for _, reg in regime_top3.iterrows():
            ma_p, cd = int(reg['ma']), int(reg['confirm'])
            regime_map = {pn: calc_regime(pd_, ma_p, cd) for pn, (pd_, _) in TSIMS.items()}

            # 7.8y + 5.25y + WF 4구간
            r_all = run_bt(a_off, d_def, a_gs_o, d_gs_d, regime_map,
                          periods=['7.8y','5.25y'] + list(WF_PERIODS.keys()))
            sc = score_combo(r_all)
            wf_cals = [r_all.get(p,{}).get('cal',0) for p in WF_PERIODS]
            wf_mean = np.mean(wf_cals) if wf_cals else 0
            wf_min = min(wf_cals) if wf_cals else 0
            wf_cv = np.std(wf_cals)/wf_mean if wf_mean > 0 else 999

            label = f'A(V{av}Q{aq}G{ag}M{am} {a_mom} {a_gs}) D(V{int(d["dV"])}Q{int(d["dQ"])}G{int(d["dG"])}M{int(d["dM"])}) MA{ma_p}_{cd}d'
            results_4.append({
                'label': label,
                'a_V':av,'a_Q':aq,'a_G':ag,'a_M':am,'a_mom':a_mom,'a_gs':a_gs,
                'd_V':int(d['dV']),'d_Q':int(d['dQ']),'d_G':int(d['dG']),'d_M':int(d['dM']),
                'd_mom':d['d_mom'],'d_gs':d['d_gs'],
                'd_E':int(d['dE']),'d_X':int(d['dX']),'d_S':int(d['dS']),
                'ma':ma_p,'confirm':cd,
                'cal_78':r_all.get('7.8y',{}).get('cal',0),
                'cal_525':r_all.get('5.25y',{}).get('cal',0),
                'score':sc, 'wf_mean':wf_mean, 'wf_min':wf_min, 'wf_cv':wf_cv,
            })

df_4 = pd.DataFrame(results_4).sort_values('score', ascending=False)
df_4.to_csv('backtest/v80_phase4_cross_validation.csv', index=False, encoding='utf-8-sig')

# WF + 인접안정성 필터
df_4_pass = df_4[(df_4['wf_min'] >= 1.5) & (df_4['wf_cv'] < 0.5)].head(10)
if len(df_4_pass) < 3:
    df_4_pass = df_4.head(10)

print(f'\n  === Phase 4 교차검증 Top 10 (WF 필터) ===')
for i, (_, r) in enumerate(df_4_pass.head(10).iterrows()):
    print(f'  {i+1}. {r["label"][:60]}')
    print(f'     7.8y={r["cal_78"]:.2f} 5.25y={r["cal_525"]:.2f} score={r["score"]:.3f} '
          f'WF_min={r["wf_min"]:.2f} WF_mean={r["wf_mean"]:.2f} CV={r["wf_cv"]:.2f}', flush=True)

# v80 후보 1위
v80_best = df_4_pass.iloc[0]
print(f'\n  ★ v80 후보 1위: score={v80_best["score"]:.3f}')
print(f'    공격: V{v80_best["a_V"]}Q{v80_best["a_Q"]}G{v80_best["a_G"]}M{v80_best["a_M"]} {v80_best["a_mom"]} {v80_best["a_gs"]}')
print(f'    방어: V{v80_best["d_V"]}Q{v80_best["d_Q"]}G{v80_best["d_G"]}M{v80_best["d_M"]} {v80_best["d_mom"]}')
print(f'    E/X/S: E{best_exs[0]}X{best_exs[1]}S{best_exs[2]} (공격) / E{v80_best["d_E"]}X{v80_best["d_X"]}S{v80_best["d_S"]} (방어)')
print(f'    국면: MA{v80_best["ma"]} {v80_best["confirm"]}d')
print(f'    WF: min={v80_best["wf_min"]:.2f} mean={v80_best["wf_mean"]:.2f} CV={v80_best["wf_cv"]:.2f}')

# v79 비교
v79_regime = DEFAULT_REGIME
v79_off = {'v':0.15,'q':0.05,'g':0.50,'m':0.30,'g_rev':0.5,'entry':3,'exit':6,'slots':3,'mom':'12m'}
v79_gs_o = ('rev_z','oca_z','gp_growth_z',0.5,0.3,0.2)
v79_def = {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,'entry':3,'exit':6,'slots':7,'mom':'6m-1m'}
v79_gs_d = ('rev_z','oca_z',None,None,None,None)
v79_r = run_bt(v79_off, v79_def, v79_gs_o, v79_gs_d, v79_regime,
               periods=['7.8y','5.25y'] + list(WF_PERIODS.keys()))
v79_sc = score_combo(v79_r)
v79_wf = [v79_r.get(p,{}).get('cal',0) for p in WF_PERIODS]

print(f'\n  v79 기준: score={v79_sc:.3f} 7.8y={v79_r["7.8y"]["cal"]:.2f} 5.25y={v79_r["5.25y"]["cal"]:.2f}')
print(f'    WF: {[round(c,2) for c in v79_wf]}')
print(f'\n  v80 vs v79 Delta:')
print(f'    score: {v80_best["score"] - v79_sc:+.3f}')
print(f'    7.8y Cal: {v80_best["cal_78"] - v79_r["7.8y"]["cal"]:+.2f}')
print(f'    5.25y Cal: {v80_best["cal_525"] - v79_r["5.25y"]["cal"]:+.2f}')

# 최종 텔레그램
total_elapsed = (time.time() - t_start) / 60
send_tg(f'<b>[v80 Phase 4] 교차검증 + WF 완료</b>\n\n'
        f'<b>v80 후보 1위:</b>\n'
        f'공격: V{v80_best["a_V"]}Q{v80_best["a_Q"]}G{v80_best["a_G"]}M{v80_best["a_M"]} {v80_best["a_mom"]} {v80_best["a_gs"]}\n'
        f'방어: V{v80_best["d_V"]}Q{v80_best["d_Q"]}G{v80_best["d_G"]}M{v80_best["d_M"]} {v80_best["d_mom"]}\n'
        f'국면: MA{v80_best["ma"]} {v80_best["confirm"]}d\n'
        f'E/X/S: E{best_exs[0]}X{best_exs[1]}S{best_exs[2]}(공격) E{v80_best["d_E"]}X{v80_best["d_X"]}S{v80_best["d_S"]}(방어)\n\n'
        f'<b>성과:</b>\n'
        f'7.8y Cal={v80_best["cal_78"]:.2f} (v79: {v79_r["7.8y"]["cal"]:.2f})\n'
        f'5.25y Cal={v80_best["cal_525"]:.2f} (v79: {v79_r["5.25y"]["cal"]:.2f})\n'
        f'WF min={v80_best["wf_min"]:.2f} mean={v80_best["wf_mean"]:.2f} CV={v80_best["wf_cv"]:.2f}\n\n'
        f'총 소요: {total_elapsed:.0f}분')

print(f'\n총 소요: {total_elapsed:.1f}분')
print('Phase 1~4 완료. Phase 5~9는 별도 스크립트로 진행.')
