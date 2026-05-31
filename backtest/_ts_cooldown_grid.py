"""TS × COOLDOWN 그리드 — v80.18 (MA20x80x5, eb=3, xb=4, slots=4, SL=-10) 고정.
사용자 통찰: TS로 팔아도 다음날 1,2위면 재매수 → 쿨다운이 TS의 진짜 레버.
쿨다운 N일: TS 퇴출 종목 N거래일 재진입 금지 (SL/rank 퇴출은 쿨다운 없음, 국면전환 시 리셋)."""
import sys, json, time
from pathlib import Path
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
ROOT=Path(r'C:\dev\claude-code\quant_py-main');STATE=ROOT/'state';DATA=ROOT/'data_cache'
PENALTY=50;TOP_N=20;EB,XB,SLOTS=3,4,4;SL=-0.10
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
def run(dates,regime,ts,cooldown,count_rebuy=False):
    pf={};pk={};eq=1.0;eh={};cd={}  # cd[tk]=재진입 가능 인덱스
    n_ts=0;n_rebuy=0
    for i,d in enumerate(dates):
        ib=regime.get(d,True);er=EB if ib else 0;xr=XB if ib else 8
        if i>=1 and pf:
            rs=[]
            for tk in pf:
                pp=gp(dates[i-1],tk);cp=gp(d,tk)
                if pp and cp: rs.append(cp/pp-1)
            if rs: eq*=(1+np.mean(rs)*len(pf)/SLOTS)
        eh[d]=eq
        if i>=1 and regime.get(dates[i-1],True)!=ib: pf.clear();pk.clear();cd.clear()
        if not ib: continue
        for tk in list(pf.keys()):
            cp=gp(d,tk);ep=pf[tk]
            if cp and ep:
                if tk in pk:
                    if cp>pk[tk]: pk[tk]=cp
                else: pk[tk]=max(cp,ep)
                if cp/ep-1<=SL: del pf[tk];pk.pop(tk,None)  # SL: 쿨다운 없음
                elif ts is not None and pk.get(tk,0)>0 and cp/pk[tk]-1<=ts:
                    del pf[tk];pk.pop(tk,None);n_ts+=1
                    if cooldown>0: cd[tk]=i+cooldown  # TS: 쿨다운
        cr0=crc.get(d,{});cr1=crc.get(dates[i-1],{}) if i>=1 else {};cr2=crc.get(dates[i-2],{}) if i>=2 else {}
        t1={tk:c for tk,c in cr1.items() if c<=TOP_N};t2={tk:c for tk,c in cr2.items() if c<=TOP_N}
        wr={tk:c0*0.4+t1.get(tk,PENALTY)*0.35+t2.get(tk,PENALTY)*0.25 for tk,c0 in cr0.items()}
        for tk in list(pf.keys()):
            if wr.get(tk,999)>xr: del pf[tk];pk.pop(tk,None)
        for tk,_ in sorted(wr.items(),key=lambda x:x[1])[:er]:
            if tk in pf: continue
            if tk in cd and i<cd[tk]: continue  # 쿨다운 중
            if len(pf)>=SLOTS: break
            cp=gp(d,tk)
            if cp:
                if count_rebuy and tk in cd: n_rebuy+=1
                pf[tk]=cp;pk[tk]=cp;cd.pop(tk,None)
    ea=np.array(list(eh.values()))
    if len(ea)<50: return 0,0,0,0,n_ts,n_rebuy
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
    return cal,cagr,mdd,min([w for w in wf if w>0] or [0]),n_ts,n_rebuy
ra=cross(adates,20,80,5);ri=cross(isd,20,80,5);ro=cross(oosd,20,80,5)
TS_G=[-0.05,-0.06,-0.07,-0.08,-0.10];CD_G=[0,1,2,3,5,10]
t0=time.time();res=[]
for ts in TS_G:
    for cdn in CD_G:
        c,cg,m,_,nts,nrb=run(adates,ra,ts,cdn,count_rebuy=True)
        ic,_,_,_,_,_=run(isd,ri,ts,cdn);oc,_,_,_,_,_=run(oosd,ro,ts,cdn)
        _,_,_,wm,_,_=run(adates,ra,ts,cdn)
        res.append({'ts':ts,'cd':cdn,'cal':c,'cagr':cg,'mdd':m,'is':ic,'oos':oc,'wfmin':wm,'nts':nts,'nrebuy':nrb})
print(f'완료 {time.time()-t0:.0f}초',flush=True)
df=pd.DataFrame(res)
print('\n=== Cal heatmap (행 TS × 열 COOLDOWN일) ===',flush=True)
print('TS\CD  '+''.join(f'{c:>8}d' for c in CD_G),flush=True)
for ts in TS_G:
    row=f'{ts*100:>4.0f}% '
    for cdn in CD_G:
        v=df[(df.ts==ts)&(df.cd==cdn)]['cal'].values[0]
        mk='*' if (ts==-0.08 and cdn==1) else ' '
        row+=f'{v:>8.3f}{mk}'
    print(row,flush=True)
print('  (* = 실전 현재 TS-8/CD1. BT 검증은 CD0 기준이었음)',flush=True)
print('\n=== MDD heatmap ===',flush=True)
print('TS\CD  '+''.join(f'{c:>8}d' for c in CD_G),flush=True)
for ts in TS_G:
    row=f'{ts*100:>4.0f}% '
    for cdn in CD_G:
        v=df[(df.ts==ts)&(df.cd==cdn)]['mdd'].values[0];row+=f'{v:>8.2f} '
    print(row,flush=True)
print('\n=== Top 12 (Cal) — IS/OOS/WFmin/재매수율 ===',flush=True)
print(f'{"#":<3}{"TS":<6}{"CD":<5}{"Cal":<8}{"CAGR":<7}{"MDD":<7}{"IS":<6}{"OOS":<6}{"WFmin":<7}{"TS매도":<7}{"즉시재매수":<8}',flush=True)
for i,r in enumerate(df.nlargest(12,'cal').to_dict('records')):
    rb_pct=f"{r['nrebuy']}/{r['nts']}" if r['nts'] else '-'
    print(f"{i+1:<3}{r['ts']*100:<5.0f}%{r['cd']:<5}{r['cal']:<8.3f}{r['cagr']:<6.1f}%{r['mdd']:<6.2f}%{r['is']:<6.2f}{r['oos']:<6.2f}{r['wfmin']:<7.2f}{r['nts']:<7}{rb_pct:<8}",flush=True)
df.to_csv(ROOT/'_ts_cooldown_results.csv',index=False,encoding='utf-8-sig')
print('\nCSV: _ts_cooldown_results.csv',flush=True)
