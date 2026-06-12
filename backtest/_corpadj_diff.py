# -*- coding: utf-8 -*-
"""보정 OFF vs ON 랭킹 diff — FG 정식 보정 검증."""
import json, sys
off=json.load(open('_tmp_off2/ranking_20260610.json',encoding='utf-8'))
on=json.load(open('_tmp_on2/ranking_20260610.json',encoding='utf-8'))
O={str(x['ticker']).zfill(6):x for x in off['rankings']}
N={str(x['ticker']).zfill(6):x for x in on['rankings']}
print(f'종목수: OFF {len(O)} / ON {len(N)}  (같아야 정상)')
common=set(O)&set(N)
only_off=set(O)-set(N); only_on=set(N)-set(O)
print(f'OFF에만: {len(only_off)}  ON에만: {len(only_on)}')

# rank 변동 (composite_rank 또는 rank)
def rk(x): return int(x.get('composite_rank', x.get('rank',999)))
moves=[]
for t in common:
    d=rk(O[t])-rk(N[t])  # +면 순위 상승(숫자 줄어듦)
    if d!=0: moves.append((t, N[t].get('name','?'), rk(O[t]), rk(N[t]), d,
                           O[t].get('momentum_s',0), N[t].get('momentum_s',0)))
moves.sort(key=lambda x:-abs(x[4]))
print(f'\ncr 바뀐 종목: {len(moves)}개. 큰 변동 상위 15:')
print(f"{'종목':<14}{'cr OFF→ON':>12}{'Δ':>5}{'momentum OFF→ON':>20}")
for t,nm,ro,rn,d,mo,mn in moves[:15]:
    arrow='↑' if d>0 else '↓'
    print(f"{nm:<14}{f'{ro}→{rn}':>12}{f'{d:+d}{arrow}':>6}{f'{mo:+.2f}→{mn:+.2f}':>20}")

# 핵심 종목 집중
print('\n=== 핵심 종목 ===')
for tk,nm in [('187870','디바이스'),('049630','재영솔루텍'),('082920','비츠로셀'),('080220','제주반도체'),('000660','SK하이닉스')]:
    if tk in O and tk in N:
        print(f"  {nm}: cr {rk(O[tk])}→{rk(N[tk])}, momentum {O[tk].get('momentum_s',0):+.2f}→{N[tk].get('momentum_s',0):+.2f}")
    elif tk in N: print(f"  {nm}: ON에만 진입 (cr {rk(N[tk])})")
    elif tk in O: print(f"  {nm}: ON에서 이탈")
    else: print(f"  {nm}: 양쪽 없음")
