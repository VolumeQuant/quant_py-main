# -*- coding: utf-8 -*-
"""제3의 융합 접근 분석 (Phase 3, 2026-06-13).
factor-overlay(가중치 문제) 대신: 교집합/확신플래그, 게이팅(veto). 데이터로 실효성 평가.
"""
import sqlite3, json, sys, io, os
import pandas as pd, numpy as np
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

PROJ = r'C:\dev\claude-code\quant_py-main'
NTM = ['ntm_90d', 'ntm_60d', 'ntm_30d', 'ntm_7d', 'ntm_current']

def load(date):
    d = json.load(open(os.path.join(PROJ, 'state', f'ranking_{date}.json'), encoding='utf-8'))
    vol = pd.DataFrame([dict(tk=x['ticker'], name=x['name'], score=x['score']) for x in d['rankings']])
    vol['vrank'] = vol['score'].rank(ascending=False, method='min').astype(int)
    con = sqlite3.connect(os.path.join(PROJ, 'kr_eps_momentum', 'eps_momentum_data_kr.db'))
    eps = pd.read_sql(f"SELECT ticker,adj_score,num_analysts,{','.join(NTM)} "
                      f"FROM ntm_screening WHERE date='{date[:4]}-{date[4:6]}-{date[6:]}'", con)
    con.close()
    eps['tk'] = eps['ticker'].str.replace('.KS', '', regex=False).str.replace('.KQ', '', regex=False)
    m = vol.merge(eps, on='tk', how='left')
    m['rel'] = m['adj_score'].notna() & (m['num_analysts'].fillna(0) >= 8) & (m[NTM] > 0).all(axis=1)
    return m

date = '20260612'
m = load(date)

# EPS 신호 상태 분류
def eps_status(r):
    if not r['rel']:
        an = r['num_analysts']
        return '커버없음' if pd.isna(an) or an < 8 else '데이터불량'
    if r['adj_score'] > 30: return '강한상향↑↑'
    if r['adj_score'] > 5: return '상향↑'
    if r['adj_score'] < -30: return '강한하향↓↓'
    if r['adj_score'] < -5: return '하향↓'
    return '중립'

print(f'=== 볼륨 top10 × EPS 신호 ({date}) ===')
print(f"{'볼륨순위':>6} {'종목':<12}{'EPS신호':<10}{'애널':>5}  접근별 처리")
top = m.sort_values('vrank').head(10)
for _, r in top.iterrows():
    st = eps_status(r)
    an = int(r['num_analysts']) if pd.notna(r['num_analysts']) else 0
    # 게이팅: 강한하향 + 신뢰 = veto 후보
    gate = '⚠️veto검토(EPS강한하향)' if st.startswith('강한하향') else (
           '✅확신++(둘다강함)' if (r['vrank'] <= 5 and st.startswith('강한상향')) else
           ('확신+(EPS상향)' if '상향' in st else ('볼륨단독(EPS무관)' if '커버없음' in st else '')))
    print(f"{r['vrank']:>6} {r['name']:<12}{st:<10}{an:>5}  {gate}")

# 접근 ① 확신플래그: 볼륨 top3가 EPS로 확인되나
print('\n=== ① 확신플래그 (볼륨 top3, 검증된 픽 안 건드리고 확신도만 부여) ===')
for _, r in m.sort_values('vrank').head(3).iterrows():
    st = eps_status(r)
    conf = 'EPS도 강세=확신UP' if '상향' in st else ('EPS커버없음=볼륨만신뢰' if '커버없음' in eps_status(r) else f'EPS={st}')
    print(f"  {r['name']}(볼륨{r['vrank']}위): {conf}")

# 접근 ② 게이팅: 볼륨 top5 중 EPS 강한하향(신뢰)으로 veto될 종목
print('\n=== ② 게이팅 (볼륨 top5 중 EPS 강한하향+신뢰 = 부실경고) ===')
g = m.sort_values('vrank').head(5)
vetoed = g[g['rel'] & (g['adj_score'] < -30)]
print(f"  veto 후보: {vetoed['name'].tolist() if len(vetoed) else '없음 (top5 모두 EPS 부실신호 없음)'}")

# 교집합 크기: 볼륨top10 ∩ EPS강한상향
print('\n=== 교집합 크기 (볼륨top15 ∩ EPS강한상향+신뢰) ===')
vol15 = set(m.sort_values('vrank').head(15)['tk'])
epsup = set(m[m['rel'] & (m['adj_score'] > 30)]['tk'])
inter = vol15 & epsup
names = m[m['tk'].isin(inter)]['name'].tolist()
print(f"  교집합 {len(inter)}종목: {names}")
