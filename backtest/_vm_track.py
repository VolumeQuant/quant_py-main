import sys, io, os, glob, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
ROOT='C:/dev'
px=pd.read_parquet(sorted(glob.glob(ROOT+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan); px=px.dropna(how='all')
tdays=[d.strftime('%Y%m%d') for d in px.index];tdi={d:i for i,d in enumerate(tdays)};parr=px.values;pcol={c:i for i,c in enumerate(px.columns)}
VM='089970'
print("[브이엠 일별 production 랭킹 + 종가 (2026-06)]")
print(f"  {'날짜':10s}{'rank':>6s}{'종가':>9s}{'전일대비':>9s}  비고")
prevp=None;rows=[]
for f in sorted(glob.glob(ROOT+'/state/ranking_*.json')):
    d=os.path.basename(f)[8:16]
    if not(d>='20260601' and d in tdi): continue
    rk=sorted(json.load(open(f,encoding='utf-8'))['rankings'],key=lambda z:z.get('rank',99))
    pos={x['ticker']:j+1 for j,x in enumerate(rk)}
    r=pos.get(VM)
    p=parr[tdi[d],pcol[VM]] if VM in pcol else None
    chg=(p/prevp-1)*100 if prevp and p else 0
    note=''
    if r is None: note='❌제외(필터/랭킹밖)'
    elif r>6: note='이탈권(>6)'
    elif r<=3: note='✅매수권'
    print(f"  {d}  {str(r) if r else '제외':>6s}{p:>8.0f}{chg:>+8.1f}%  {note}")
    rows.append((d,r,p));prevp=p
# 이탈/재진입 분석: rank<=3 진입 후 >6 또는 제외되는 빈도
print("\n[이탈 사고]")
inpos=False;entry=None;exits=0
for d,r,p in rows:
    held = r is not None and r<=6
    if not inpos and r is not None and r<=3: inpos=True;entry=(d,p);print(f"  진입 {d} @ {p:.0f}")
    elif inpos and (r is None or r>6):
        inpos=False;exits+=1
        print(f"  이탈 {d} @ {p:.0f} (진입대비 {(p/entry[1]-1)*100:+.0f}%) — {'제외' if r is None else f'rank {r}'}")
print(f"\n  총 이탈 {exits}회")
