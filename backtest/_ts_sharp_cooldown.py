"""급락 TS 분해 + 조건부 쿨다운 실험 (v80.18, eb3/xb4/slots4, SL-10).
급락 = TS 퇴출일 당일 낙폭(cp/전일종가-1) ≤ thr.
가설: 급락으로 걸린 것만 하루 대기가 알파, 완만한 되돌림은 다음날이 더 비쌈."""
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

def run(dates,regime,ts,cd_days,sharp_thr=None,collect=False):
    """sharp_thr=None: cd_days를 모든 TS퇴출에 적용. 값 지정: 당일낙폭<=sharp_thr 일 때만 cd_days, 아니면 즉시 재매수 허용."""
    pf={};pk={};eq=1.0;eh={};cd={};entry_px={}
    cases=[]
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
                if cp/ep-1<=SL: del pf[tk];pk.pop(tk,None)
                elif ts is not None and pk.get(tk,0)>0 and cp/pk[tk]-1<=ts:
                    # 당일 낙폭
                    pp=gp(dates[i-1],tk) if i>=1 else None
                    day_drop=(cp/pp-1) if pp else 0
                    apply_cd = cd_days if (sharp_thr is None or day_drop<=sharp_thr) else 0
                    if collect: cases.append({'tk':tk,'exit_i':i,'day_drop':day_drop,'exit_px':cp,'sharp':(day_drop<=(sharp_thr or -0.05))})
                    del pf[tk];pk.pop(tk,None)
                    if apply_cd>0: cd[tk]=i+apply_cd
        cr0=crc.get(d,{});cr1=crc.get(dates[i-1],{}) if i>=1 else {};cr2=crc.get(dates[i-2],{}) if i>=2 else {}
        t1={tk:c for tk,c in cr1.items() if c<=TOP_N};t2={tk:c for tk,c in cr2.items() if c<=TOP_N}
        wr={tk:c0*0.4+t1.get(tk,PENALTY)*0.35+t2.get(tk,PENALTY)*0.25 for tk,c0 in cr0.items()}
        for tk in list(pf.keys()):
            if wr.get(tk,999)>xr: del pf[tk];pk.pop(tk,None)
        for tk,_ in sorted(wr.items(),key=lambda x:x[1])[:er]:
            if tk in pf: continue
            if tk in cd and i<cd[tk]: continue
            if len(pf)>=SLOTS: break
            cp=gp(d,tk)
            if cp: pf[tk]=cp;pk[tk]=cp;cd.pop(tk,None)
    ea=np.array(list(eh.values()))
    if len(ea)<50: return (0,0,0,0,cases)
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
    return (cal,cagr,mdd,min([w for w in wf if w>0] or [0]),cases)
ra=cross(adates,20,80,5);ri=cross(isd,20,80,5);ro=cross(oosd,20,80,5)

# === Part A: 급락 vs 완만 분해 (CD0 기준으로 모든 TS퇴출 + 다음날 재매수 효과) ===
# CD0 baseline에서 TS퇴출 케이스 수집 후, 각각 '다음날 재매수했다면' 효과 측정
_,_,_,_,cases=run(adates,ra,-0.08,0,sharp_thr=None,collect=True)
rows=[]
for c in cases:
    i=c['exit_i'];nx=i+1
    if nx<len(adates):
        rebuy=gp(adates[nx],c['tk'])
        if rebuy: rows.append({'day_drop':c['day_drop'],'rebuy_vs_exit':rebuy/c['exit_px']-1})
A=pd.DataFrame(rows)
print(f"\n=== Part A: TS퇴출 {len(A)}건 — 당일낙폭별 '다음날 재매수가 vs 퇴출가' ===")
print(f"{'당일낙폭 구간':<16}{'건수':>5}{'다음날 평균':>12}{'더쌈비율':>9}")
for lo,hi,lbl in [(-1,-0.07,'≤ -7% (급락)'),(-0.07,-0.05,'-7%~-5%'),(-0.05,-0.03,'-5%~-3%'),(-0.03,1,'> -3% (완만)')]:
    s=A[(A.day_drop>lo)&(A.day_drop<=hi)]
    if len(s):
        print(f"{lbl:<16}{len(s):>5}{s.rebuy_vs_exit.mean()*100:>+11.2f}%{(s.rebuy_vs_exit<0).mean()*100:>8.0f}%")
print("→ 음수(평균)일수록 = 다음날 기다리면 더 싸게 재매수 = 하루 대기 유리")

# === Part B: 조건부 쿨다운 전략 그리드 ===
print(f"\n=== Part B: 전략 그리드 (Cal/MDD/IS/OOS/WFmin) ===")
print(f"{'전략':<28}{'Cal':>7}{'MDD':>7}{'IS':>6}{'OOS':>6}{'WFmin':>7}")
def ev(ts,cd,sharp,label):
    c,cg,m,_,_=run(adates,ra,ts,cd,sharp)
    ic,_,_,_,_=run(isd,ri,ts,cd,sharp);oc,_,_,_,_=run(oosd,ro,ts,cd,sharp)
    _,_,_,wm,_=run(adates,ra,ts,cd,sharp)
    print(f"{label:<28}{c:>7.3f}{m:>6.2f}%{ic:>6.2f}{oc:>6.2f}{wm:>7.2f}",flush=True)
    return c
print("--- TS-8% 기준 쿨다운 방식 비교 ---")
ev(-0.08,0,None,"TS-8 CD0 (현재 실전)")
ev(-0.08,1,None,"TS-8 CD1 전체적용")
ev(-0.08,1,-0.07,"TS-8 CD1 급락만(≤-7%)")
ev(-0.08,1,-0.05,"TS-8 CD1 급락만(≤-5%)")
ev(-0.08,1,-0.03,"TS-8 CD1 급락만(≤-3%)")
ev(-0.08,2,-0.05,"TS-8 CD2 급락만(≤-5%)")
ev(-0.08,2,-0.07,"TS-8 CD2 급락만(≤-7%)")
print("--- TS 레벨별 (급락≤-5% CD1) ---")
for ts in [-0.06,-0.07,-0.08,-0.10]:
    ev(ts,1,-0.05,f"TS{ts*100:.0f} CD1 급락만(≤-5%)")
print("--- TS 레벨별 (전체 CD1, 비교용) ---")
for ts in [-0.06,-0.07,-0.08,-0.10]:
    ev(ts,1,None,f"TS{ts*100:.0f} CD1 전체")
