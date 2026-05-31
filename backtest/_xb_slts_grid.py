"""xb × SL × TS 동시 그리드 — v80.18 (MA20x80x5, eb=3, slots=4) 고정.
rank-exit(xb)이 주력이므로 xb를 풀면 SL/TS 작동 여지↑. 진짜 상호작용 탐색."""
import sys, json, time
from pathlib import Path
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
ROOT=Path(r'C:\dev\claude-code\quant_py-main');STATE=ROOT/'state';DATA=ROOT/'data_cache'
PENALTY=50;TOP_N=20;EB,SLOTS=3,4
ohlcv=pd.read_parquet(sorted(DATA.glob('all_ohlcv_2017*.parquet'))[-1]).replace(0,np.nan)
kospi=pd.read_parquet(str(DATA/'kospi_yf.parquet')).iloc[:,0].sort_index()
def cross(dates,short,lp,cf):
    sma=kospi.rolling(short).mean();lma=kospi.rolling(lp).mean();reg={};md=False;stk=0;ss=None
    for d in dates:
        ts=pd.Timestamp(d);sv=sma.get(ts);lv=lma.get(ts)
        if sv is None or pd.isna(sv) or pd.isna(lv): reg[d]=md;continue
        s=sv>lv
        if s==ss: stk+=1
        else: stk=1;ss=s
        if stk>=cf and md!=s: md=s
        reg[d]=md
    return reg
def gp(d,tk):
    ts=pd.Timestamp(d)
    if ts not in ohlcv.index:
        idx=ohlcv.index.searchsorted(ts)
        if idx>=len(ohlcv): return None
        ts=ohlcv.index[idx]
    if tk not in ohlcv.columns: return None
    v=ohlcv.loc[ts,tk];return v if pd.notna(v) and v>0 else None
def lcr(d):
    fp=STATE/f'ranking_{d}.json'
    if not fp.exists(): return {}
    data=json.load(open(fp,encoding='utf-8'))
    return {str(r['ticker']).zfill(6):r.get('composite_rank',r.get('rank',999)) for r in data['rankings']}
adates=sorted([fp.stem.replace('ranking_','') for fp in STATE.glob('ranking_*.json') if fp.stem.replace('ranking_','').isdigit() and len(fp.stem.replace('ranking_',''))==8 and '20190102'<=fp.stem.replace('ranking_','')<='20260522'])
crc={d:lcr(d) for d in adates}
isd=[d for d in adates if d<='20221231'];oosd=[d for d in adates if d>='20230102']
print(f'대상 {len(adates)}일',flush=True)
def run(dates,regime,xb,sl,ts):
    pf={};pk={};eq=1.0;eh={}
    for i,d in enumerate(dates):
        ib=regime.get(d,True);er=EB if ib else 0;xr=xb if ib else 8
        if i>=1 and pf:
            rs=[]
            for tk in pf:
                pp=gp(dates[i-1],tk);cp=gp(d,tk)
                if pp and cp: rs.append(cp/pp-1)
            if rs: eq*=(1+np.mean(rs)*len(pf)/SLOTS)
        eh[d]=eq
        if i>=1 and regime.get(dates[i-1],True)!=ib: pf.clear();pk.clear()
        if not ib: continue
        for tk in list(pf.keys()):
            cp=gp(d,tk);ep=pf[tk]
            if cp and ep:
                if tk in pk:
                    if cp>pk[tk]: pk[tk]=cp
                else: pk[tk]=max(cp,ep)
                if sl is not None and cp/ep-1<=sl: del pf[tk];pk.pop(tk,None)
                elif ts is not None and pk.get(tk,0)>0 and cp/pk[tk]-1<=ts: del pf[tk];pk.pop(tk,None)
        cr0=crc.get(d,{});cr1=crc.get(dates[i-1],{}) if i>=1 else {};cr2=crc.get(dates[i-2],{}) if i>=2 else {}
        t1={tk:c for tk,c in cr1.items() if c<=TOP_N};t2={tk:c for tk,c in cr2.items() if c<=TOP_N}
        wr={tk:c0*0.4+t1.get(tk,PENALTY)*0.35+t2.get(tk,PENALTY)*0.25 for tk,c0 in cr0.items()}
        for tk in list(pf.keys()):
            if wr.get(tk,999)>xr: del pf[tk];pk.pop(tk,None)
        for tk,_ in sorted(wr.items(),key=lambda x:x[1])[:er]:
            if tk in pf: continue
            if len(pf)>=SLOTS: break
            cp=gp(d,tk)
            if cp: pf[tk]=cp;pk[tk]=cp
    ea=np.array(list(eh.values()))
    if len(ea)<50: return 0,0,0,0
    cagr=(ea[-1]**(252/len(ea))-1)*100
    p=np.maximum.accumulate(ea);mdd=-((ea-p)/p).min()*100
    cal=cagr/mdd if mdd>0 else 0
    wf=[]
    for st,ed in [('20190102','20191231'),('20200101','20211231'),('20220101','20231231'),('20240101','20260522')]:
        es=pd.Series(eh);sub=es[(es.index>=st)&(es.index<=ed)]
        if len(sub)<50: wf.append(0);continue
        sr=(sub.iloc[-1]/sub.iloc[0])**(252/len(sub))-1
        sp=np.maximum.accumulate(sub.values);sd=-((sub.values-sp)/sp).min()
        wf.append((sr*100)/(sd*100) if sd>0 else 0)
    return cal,cagr,mdd,min([w for w in wf if w>0] or [0])
ra=cross(adates,20,80,5);ri=cross(isd,20,80,5);ro=cross(oosd,20,80,5)
XB_G=[3,4,5,6,7,8]; SL_G=[-0.07,-0.10,-0.15]; TS_G=[None,-0.05,-0.06,-0.07,-0.08,-0.10,-0.15]
t0=time.time();res=[]
for xb in XB_G:
    for sl in SL_G:
        for ts in TS_G:
            c,cg,m,_=run(adates,ra,xb,sl,ts)
            ic,_,_,_=run(isd,ri,xb,sl,ts)
            oc,_,_,_=run(oosd,ro,xb,sl,ts)
            _,_,_,wm=run(adates,ra,xb,sl,ts)
            sc=c*0.3+ic*0.2+oc*0.2+wm*0.2+(10/m if m>0 else 0)*0.1
            res.append({'xb':xb,'sl':sl,'ts':ts,'cal':c,'cagr':cg,'mdd':m,'is':ic,'oos':oc,'wfmin':wm,'score':sc})
print(f'완료 {time.time()-t0:.0f}초, {len(res)} 시나리오',flush=True)
df=pd.DataFrame(res)
def f(x): return 'none' if x is None else f'{x*100:.0f}%'
print('\n=== xb별 최적 TS (SL=-10 고정) Cal heatmap (행 xb × 열 TS) ===',flush=True)
sub=df[df.sl==-0.10]
print('xb\TS '+''.join(f'{f(ts):>8}' for ts in TS_G),flush=True)
for xb in XB_G:
    row=f'{xb:<5} '
    for ts in TS_G:
        v=sub[(sub.xb==xb)&(sub.ts.apply(lambda x:x==ts))]['cal'].values
        row+=f'{v[0]:>8.3f}' if len(v) else '     -  '
    mark=' ← v80.18' if xb==4 else ''
    print(row+mark,flush=True)
print('\n=== Top 20 (종합 점수) ===',flush=True)
print(f'{"#":<3}{"xb":<4}{"SL":<6}{"TS":<6}{"Cal":<8}{"CAGR":<7}{"MDD":<7}{"IS":<6}{"OOS":<6}{"WFmin":<6}{"점수":<7}',flush=True)
for i,r in enumerate(df.nlargest(20,'score').to_dict('records')):
    cur=' ←현재' if (r['xb']==4 and r['sl']==-0.10 and r['ts']==-0.08) else ''
    print(f"{i+1:<3}{r['xb']:<4}{f(r['sl']):<6}{f(r['ts']):<6}{r['cal']:<8.3f}{r['cagr']:<6.1f}%{r['mdd']:<6.2f}%{r['is']:<6.2f}{r['oos']:<6.2f}{r['wfmin']:<6.2f}{r['score']:<7.3f}{cur}",flush=True)
print('\n=== Cal Top 10 ===',flush=True)
for i,r in enumerate(df.nlargest(10,'cal').to_dict('records')):
    print(f"{i+1:<3} xb={r['xb']} SL={f(r['sl'])} TS={f(r['ts'])} → Cal {r['cal']:.3f} MDD {r['mdd']:.2f}% IS {r['is']:.2f} OOS {r['oos']:.2f} WFmin {r['wfmin']:.2f}",flush=True)
print('\n=== 현재 (xb4/SL-10/TS-8) ===',flush=True)
cr=df[(df.xb==4)&(df.sl==-0.10)&(df.ts.apply(lambda x:x==-0.08))].to_dict('records')[0]
print(f"Cal {cr['cal']:.3f} CAGR {cr['cagr']:.1f}% MDD {cr['mdd']:.2f}% IS {cr['is']:.2f} OOS {cr['oos']:.2f} WFmin {cr['wfmin']:.2f} 점수 {cr['score']:.3f}",flush=True)
dfs=df.copy();dfs['sl']=dfs['sl'].apply(f);dfs['ts']=dfs['ts'].apply(f)
dfs.to_csv(ROOT/'_xb_slts_results.csv',index=False,encoding='utf-8-sig')
print(f'\nCSV: _xb_slts_results.csv',flush=True)
