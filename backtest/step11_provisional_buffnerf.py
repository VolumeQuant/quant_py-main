"""잠정실적 활용 방법 B: 버프/너프 (wr 보너스)

기존 Growth 팩터 안 건드림. weighted_rank 후처리에서 보너스/페널티만 적용.
cross-section 왜곡 없음, ranking 재생성 불필요.

탐색:
  보너스 크기 × YoY 기준 × 지속 기간
"""
import sys, os, json, glob, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd, numpy as np
from turbo_simulator import TurboSimulator
from pathlib import Path
from copy import deepcopy

PROJECT = Path(__file__).parent.parent

# 데이터 로드
print('데이터 로드...', flush=True)
def load_rankings(dirs):
    data = {}
    for d in dirs:
        d = Path(d)
        if not d.exists(): continue
        for fp in sorted(d.glob('ranking_*.json')):
            k = fp.stem.replace('ranking_', '')
            if len(k) != 8: continue
            if k not in data:
                with open(fp, 'r', encoding='utf-8') as f: data[k] = json.load(f)
    return data

boost = load_rankings([PROJECT/'backtest'/'bt_extended', PROJECT/'state'])
defense = load_rankings([PROJECT/'backtest'/'bt_extended_defense', PROJECT/'state'/'defense'])
dates = sorted(set(boost) & set(defense))
base_rk = {d: boost[d]['rankings'] for d in dates}

ohlcv = pd.read_parquet(sorted((PROJECT/'data_cache').glob('all_ohlcv_2017*.parquet'))[-1]).replace(0, np.nan)
kospi_df = pd.read_parquet(PROJECT/'data_cache'/'kospi_yf.parquet')
kospi = kospi_df.iloc[:, 0].fillna(kospi_df['kospi']).sort_index()
ma170 = kospi.rolling(170).mean()

# 잠정실적 로드
prov_df = pd.read_parquet(PROJECT/'data_cache'/'provisional_earnings.parquet')
prov_df['rcept_dt'] = pd.to_datetime(prov_df['rcept_dt'])
prov_df['base_date'] = pd.to_datetime(prov_df['base_date'])

# 잠정실적 YoY 계산 (같은 종목 전년동기 대비)
# 이전 분기 매출 대비로 간단 계산 (정확한 YoY는 데이터 부족)
print(f'잠정실적: {len(prov_df)}건', flush=True)

# 종목별 잠정 이벤트: {date_str: {ticker: op_income_yoy}}
# 잠정 공시일 기준으로 이벤트 생성
prov_events = {}  # date_str → [(ticker, revenue, op_income)]
for _, row in prov_df.iterrows():
    d = row['rcept_dt'].strftime('%Y%m%d')
    if d not in prov_events:
        prov_events[d] = []
    prov_events[d].append({
        'ticker': row['ticker'],
        'revenue': row.get('revenue'),
        'op_income': row.get('operating_income'),
    })

print(f'잠정 이벤트 날짜: {len(prov_events)}일', flush=True)

# 국면
def calc_regime(target_dates):
    reg = {}; md = False; stk = 0; ss = None
    for d in target_dates:
        ts = pd.Timestamp(d); kv = kospi.get(ts); mv = ma170.get(ts)
        if kv is None or pd.isna(mv): reg[d] = md; continue
        s = kv > mv
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= 8 and md != s: md = s
        reg[d] = md
    return reg

# TurboSim
PERIODS = {
    '7.8y': ('20180702','20260414'),
    '5.25y': ('20210104','20260414'),
}
WF = {'2018H2-19':('20180702','20191231'),'2020-21':('20200102','20211230'),
      '2022-23':('20220103','20231228'),'2024-26':('20240102','20260414')}

V80_O = {'v':0.15,'q':0.00,'g':0.55,'m':0.30,'g_rev':0.6,'entry':3,'exit':6,'slots':3,'mom':'12m'}
V80_D = {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,'entry':3,'exit':6,'slots':5,'mom':'6m-1m'}
GS = ('rev_z','oca_z',None,None,None,None)


def apply_buff_nerf(rankings_dict, buff_size, nerf_size, duration_days=45):
    """잠정 공시 종목에 wr 보너스/페널티 적용한 새 rankings 반환"""
    new_rk = {}
    # 활성 버프/너프 추적: {ticker: (end_date, bonus)}
    active = {}

    for d in sorted(rankings_dict.keys()):
        ts = pd.Timestamp(d)

        # 오늘 새로 공시된 잠정실적 확인
        if d in prov_events:
            for ev in prov_events[d]:
                tk = ev['ticker']
                op = ev.get('op_income')
                if op is not None and op > 0:
                    # 양수 영업이익 → 버프
                    end = (ts + pd.Timedelta(days=duration_days)).strftime('%Y%m%d')
                    active[tk] = (end, buff_size)
                elif op is not None and op < 0:
                    # 음수 영업이익 → 너프
                    end = (ts + pd.Timedelta(days=duration_days)).strftime('%Y%m%d')
                    active[tk] = (end, nerf_size)

        # 만료된 버프/너프 제거
        expired = [tk for tk, (end, _) in active.items() if end <= d]
        for tk in expired:
            del active[tk]

        # ranking 복사 + 보너스 적용
        items = deepcopy(rankings_dict[d])
        for item in items:
            tk = item.get('ticker', '')
            if tk in active:
                _, bonus = active[tk]
                item['weighted_rank'] = max(0.1, item.get('weighted_rank', 50) + bonus)

        # 보너스 적용 후 재정렬
        items.sort(key=lambda x: x.get('weighted_rank', 999))
        for i, item in enumerate(items):
            item['rank'] = i + 1

        new_rk[d] = items

    return new_rk


def run_score(rk_data, periods=None):
    if periods is None: periods = ['7.8y', '5.25y']
    res = {}
    for pname in periods:
        ps, pe = {**PERIODS, **WF}[pname]
        pd_ = [d for d in dates if ps <= d <= pe and d in rk_data]
        if len(pd_) < 20: continue
        tsim = TurboSimulator({d: rk_data[d] for d in pd_}, pd_, ohlcv)
        reg = calc_regime(pd_)
        r = tsim.run_regime(defense_params=V80_D, offense_params=V80_O,
            regime_dict=reg, trailing_stop=-0.15,
            g_sub1_o=GS[0],g_sub2_o=GS[1],g_sub3_o=GS[2],
            g_w1_o=GS[3],g_w2_o=GS[4],g_w3_o=GS[5],
            g_sub1_d=GS[0],g_sub2_d=GS[1],g_sub3_d=GS[2],
            g_w1_d=GS[3],g_w2_d=GS[4],g_w3_d=GS[5])
        res[pname] = r
    return res


# ════════════════════════════════════════
# 테스트: 다양한 버프/너프 크기
# ════════════════════════════════════════
print('\n=== 버프/너프 그리드 테스트 ===', flush=True)

# baseline
bl_res = run_score(base_rk, list(PERIODS.keys()) + list(WF.keys()))
bl_78 = bl_res['7.8y']['calmar']
bl_525 = bl_res['5.25y']['calmar']
bl_sc = (bl_78 * bl_525) ** 0.5
print(f'baseline: 7.8y={bl_78:.2f} 5.25y={bl_525:.2f} score={bl_sc:.3f}\n', flush=True)

results = []
for buff in [-0.5, -1.0, -1.5, -2.0, -3.0]:
    for nerf in [0, 0.5, 1.0, 2.0]:
        for dur in [30, 45]:
            modified_rk = apply_buff_nerf(base_rk, buff, nerf, dur)
            res = run_score(modified_rk)
            c78 = res.get('7.8y',{}).get('calmar',0)
            c525 = res.get('5.25y',{}).get('calmar',0)
            sc = (c78*c525)**0.5 if c78>0 and c525>0 else 0
            delta = sc - bl_sc
            results.append({
                'buff': buff, 'nerf': nerf, 'dur': dur,
                'cal_78': c78, 'cal_525': c525, 'score': sc, 'delta': delta,
            })
            marker = ' ★' if delta > 0.1 else ''
            print(f'  buff={buff:+.1f} nerf={nerf:+.1f} dur={dur}d: '
                  f'7.8y={c78:.2f} 5.25y={c525:.2f} score={sc:.3f} (Δ{delta:+.3f}){marker}', flush=True)

df = pd.DataFrame(results).sort_values('score', ascending=False)
print(f'\n=== Top 10 ===')
for i, (_, r) in enumerate(df.head(10).iterrows()):
    print(f'  {i+1}. buff={r["buff"]:+.1f} nerf={r["nerf"]:+.1f} dur={r["dur"]}d: '
          f'score={r["score"]:.3f} (Δ{r["delta"]:+.3f})')

# 최고가 baseline보다 좋은지?
best = df.iloc[0]
print(f'\n=== 결론 ===')
print(f'baseline: score={bl_sc:.3f}')
print(f'best:     score={best["score"]:.3f} (buff={best["buff"]} nerf={best["nerf"]} dur={best["dur"]})')
print(f'Delta:    {best["delta"]:+.3f}')
if best['delta'] > 0:
    print('→ 버프/너프가 baseline 개선!')
    # WF 검증
    mod_rk = apply_buff_nerf(base_rk, best['buff'], best['nerf'], int(best['dur']))
    wf_res = run_score(mod_rk, list(WF.keys()))
    wf_cals = [wf_res.get(p,{}).get('calmar',0) for p in WF]
    print(f'WF: [{", ".join(f"{c:.2f}" for c in wf_cals)}] min={min(wf_cals):.2f}')
else:
    print('→ 버프/너프도 baseline 개선 못함')

df.to_csv(str(PROJECT/'backtest'/'step11_buffnerf_results.csv'), index=False, encoding='utf-8-sig')
print(f'\n저장: backtest/step11_buffnerf_results.csv')
