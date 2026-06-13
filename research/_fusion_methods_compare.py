# -*- coding: utf-8 -*-
"""더 좋은 융합방법 비교 (Phase 2, 2026-06-13).
현재 additive-score 대비 대안들 메커니즘·robustness 비교. (BT 불가 → 메커니즘+견고성 평가)
"""
import sqlite3, json, sys, io, glob
import pandas as pd, numpy as np
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

PROJ = r'C:\dev\claude-code\quant_py-main'
DB = PROJ + r'\kr_eps_momentum\eps_momentum_data_kr.db'
NTM = ['ntm_90d', 'ntm_60d', 'ntm_30d', 'ntm_7d', 'ntm_current']

def load(date):
    d = json.load(open(f'{PROJ}\\state\\ranking_{date}.json', encoding='utf-8'))
    vol = pd.DataFrame([dict(tk=x['ticker'], name=x['name'], score=x['score'],
                             vrank=x['composite_rank']) for x in d['rankings']])
    con = sqlite3.connect(DB)
    eps = pd.read_sql(f"SELECT ticker,adj_score,score as eps_raw,eps_chg_weighted,num_analysts,{','.join(NTM)} "
                      f"FROM ntm_screening WHERE date='{date[:4]}-{date[4:6]}-{date[6:]}'", con)
    con.close()
    eps['tk'] = eps['ticker'].str.replace('.KS', '', regex=False).str.replace('.KQ', '', regex=False)
    m = vol.merge(eps, on='tk', how='left')
    m['rel'] = (m['adj_score'].notna() & (m['num_analysts'].fillna(0) >= 8)
                & (m[NTM] > 0).all(axis=1))
    return m

def zsig(m, col):
    r = m['rel']
    mu, sd = m.loc[r, col].mean(), m.loc[r, col].std()
    return np.where(r, np.clip((m[col]-mu)/sd, -2, 2), 0.0)

date = '20260612'
m = load(date)
print(f'=== 융합방법 비교 ({date}, 신뢰종목 {int(m["rel"].sum())}) ===\n')

# EPS 신호 3종 직교성 (볼륨 score와 상관 — 낮을수록 새정보)
print('[1] EPS 신호별 볼륨score 상관 (낮을수록 직교=새정보)')
for col in ['adj_score', 'eps_raw', 'eps_chg_weighted']:
    rr = m[m['rel']]
    print(f'   {col:18}: corr {rr["score"].corr(rr[col]):+.2f}')

m['z'] = zsig(m, 'adj_score')
vt = list(m.sort_values('score', ascending=False).head(3)['name'])
print(f'\n[2] 볼륨 단독 top3: {vt}\n')

# 방법 A: 현재 additive score
mA = m.copy(); mA['f'] = mA['score'] + 0.2*mA['z']
# 방법 B: rank-based — EPS z를 ±2랭크 보너스로 (bounded, 검증된 볼륨순위 base 보존)
mB = m.copy()
mB['vrk'] = mB['score'].rank(ascending=False)
mB['frk'] = mB['vrk'] - 1.5*mB['z']   # z=+2 → 3랭크↑, z=-2 → 3랭크↓ (제한적)
# 방법 C: conditional tie-break — 볼륨 상위3은 고정, 4위~10위만 EPS로 재배열
mC = m.copy(); mC['vrk'] = mC['score'].rank(ascending=False)
contested = (mC['vrk'] >= 4) & (mC['vrk'] <= 12)
mC['f'] = mC['score'] + np.where(contested, 0.2*mC['z'], 0.0)

for nm, df, key, asc in [('A 현재(additive)', mA, 'f', False),
                          ('B rank-bounded', mB, 'frk', True),
                          ('C conditional(top3고정)', mC, 'f', False)]:
    t3 = list(df.sort_values(key, ascending=asc).head(3)['name'])
    chg = '동일' if set(t3) == set(vt) else f"변화: {set(t3)^set(vt)}"
    print(f'  [{nm}] top3: {t3}  ({chg})')

# robustness: 가중치 0.1~0.5 흔들 때 top3 안정성 (현재 additive)
print('\n[3] robustness — 가중치 흔들 때 top3 변하나 (additive)')
for w in [0.1, 0.2, 0.3, 0.5]:
    t3 = m.assign(_f=m['score']+w*m['z']).sort_values('_f', ascending=False).head(3)['name'].tolist()
    print(f'   w={w}: {t3}')

# 여러 날 방법 발산 체크
print('\n[4] 다른 날 방법별 top3 발산하나 (A additive vs B rank-bounded)')
for d2 in ['20260609', '20260611', '20260612']:
    try:
        mm = load(d2)
    except Exception:
        continue
    mm['z'] = zsig(mm, 'adj_score')
    vt2 = mm.sort_values('score', ascending=False).head(3)['name'].tolist()
    A = mm.assign(_f=mm['score']+0.2*mm['z']).sort_values('_f', ascending=False).head(3)['name'].tolist()
    vrk = mm['score'].rank(ascending=False)
    B = mm.assign(_r=vrk-1.5*mm['z']).sort_values('_r').head(3)['name'].tolist()
    print(f'   {d2}: 볼륨={vt2} | A={A} | B={B} | {"동일" if A==B else "발산!"}')
