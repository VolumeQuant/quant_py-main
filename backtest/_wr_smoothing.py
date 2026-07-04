# -*- coding: utf-8 -*-
"""wr 평활 다각도 실험: 펀더/가격 분리평활 + wr축소 + 비대칭. baseline=production wr(rank 3일)."""
import sys,io,os,glob,json
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
import numpy as np,pandas as pd
R='C:/dev/claude-code/quant_py-main'
px=pd.read_parquet(R+'/data_cache/all_ohlcv_adj_20170601_20260629.parquet').replace(0,np.nan)
pcol={c:i for i,c in enumerate(px.columns)};parr=px.values
tdays=[d.strftime('%Y%m%d') for d in px.index];tdi={d:i for i,d in enumerate(tdays)}
kc=pd.read_parquet(R+'/data_cache/kospi_yf.parquet').iloc[:,0];ma20=kc.rolling(20).mean();ma80=kc.rolling(80).mean()
ohlcv=pd.read_parquet(R+'/data_cache/all_ohlcv_20170601_20260629.parquet').replace(0,np.nan)
ohv=ohlcv.values; ohc={c:i for i,c in enumerate(ohlcv.columns)}; ohd=[d.strftime('%Y%m%d') for d in ohlcv.index]; ohdi={d:i for i,d in enumerate(ohd)}
def mom5_z(dt):
    i=ohdi.get(dt)
    if i is None:
        cand=[d for d in ohd if d<=dt]
        if not cand: return {}
        i=ohdi[cand[-1]]
    rows=[r for r in range(max(0,i-8),i+1) if np.isfinite(ohv[r]).sum()>=ohv.shape[1]*0.5]
    if len(rows)<6: return {}
    raw=ohv[rows[-1]]/ohv[rows[-6]]-1; raw=np.where(np.isfinite(raw),raw,np.nan)
    m=np.nanmean(raw); s=np.nanstd(raw)
    if not s>0: return {}
    z=(raw-m)/s
    return {c:z[ohc[c]] for c in ohlcv.columns if np.isfinite(z[ohc[c]])}
# 로드: 종목별 slow/fast/score
DAT={};dts=[]
for f in sorted(glob.glob(R+'/state/ranking_*.json')):
    dt=os.path.basename(f)[8:16]
    if not(dt.isdigit() and len(dt)==8 and dt>='20190102' and dt in tdi): continue
    r=json.load(open(f,encoding='utf-8'))['rankings']
    z5=mom5_z(dt); d={}
    for x in r:
        t=x['ticker']
        slow=x.get('value_s',0)*0.15+x.get('growth_s',0)*0.55+x.get('momentum_s',0)*0.30
        fast=(x.get('mom_10_z') or 0)*0.05+(x.get('vol_low_z') or 0)*0.06+(x.get('overheat_pen') or 0)*0.2
        d[t]={'slow':slow,'fast':fast,'m5':z5.get(t,0.0),'score':x.get('score',0),'gate':x.get('score',0)<-900}
    DAT[dt]=d; dts.append(dt)
dts=sorted(dts)
reg={};md=True;stk=0;ss=None
for dd in dts:
    ts=pd.Timestamp(dd[:4]+'-'+dd[4:6]+'-'+dd[6:])
    if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[dd]=md;continue
    s=bool(ma20[ts]>ma80[ts]);stk=stk+1 if s==ss else 1;ss=s
    if stk>=5 and md!=s: md=s
    reg[dd]=md
def run(final_score_fn, sub=None):
    """final_score_fn(k) -> {ticker: score}; E3X6S3 매매룰"""
    held=[];out=[];prev=None
    for k,d in enumerate(dts):
        ret=0.0
        if held and prev:
            rr=[parr[tdi[d],pcol[t]]/parr[tdi[prev],pcol[t]]-1 for t in held if t in pcol and parr[tdi[prev],pcol[t]]>0 and parr[tdi[d],pcol[t]]>0]
            ret=np.mean(rr) if rr else 0.0
        out.append((d,ret))
        if not reg.get(d,True): held=[]; prev=d; continue
        fs=final_score_fn(k)
        ranked=sorted(fs.items(),key=lambda x:-x[1])
        rank={t:i+1 for i,(t,_) in enumerate(ranked)}
        held=[t for t in held if rank.get(t,999)<=6]
        for t,_ in ranked:
            if len(held)>=3: break
            if rank[t]<=3 and t not in held: held.append(t)
        prev=d
    a=np.array([r for dd,r in out if (not sub or sub[0]<=dd<=sub[1])])
    if len(a)<20: return 0,0,0
    eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return cagr,mdd,(cagr/abs(mdd) if mdd<0 else 0)
def val(k,t,key):  # lag k의 종목 t 값 (없으면 None)
    if k<0: return None
    return DAT[dts[k]].get(t,{}).get(key)
def universe(k): return set(DAT[dts[k]].keys())
# rank 평활(production wr) 재현용: cr = score 순위
CR={}
for d in dts:
    sc=sorted(DAT[d].items(),key=lambda x:-x[1]['score'])
    CR[d]={t:i+1 for i,(t,_) in enumerate(sc)}
def crv(k,t):
    if k<0: return 50.0
    r=CR[dts[k]].get(t,999); return r if r<=20 else 50.0
# --- 방식들 ---
def f_prod_wr(k):  # baseline: cr rank 3일 가중 → -wr (score 높을수록)
    d=dts[k]; res={}
    for t in universe(k):
        if DAT[d][t]['gate']: continue
        if CR[d].get(t,999)>50: continue
        res[t]=-(0.4*crv(k,t)+0.35*crv(k-1,t)+0.25*crv(k-2,t))
    return res
def make_split(sw, mw):  # slow 3일평활(0.4/0.35/0.25) + fast 당일 + mw*mom5 당일
    def fn(k):
        d=dts[k]; res={}
        for t in universe(k):
            if DAT[d][t]['gate']: continue
            s0=DAT[d][t]['slow']; s1=val(k-1,t,'slow'); s2=val(k-2,t,'slow')
            s1=s0 if s1 is None else s1; s2=s0 if s2 is None else s2
            slow_sm=0.4*s0+0.35*s1+0.25*s2
            res[t]=slow_sm + DAT[d][t]['fast'] + mw*DAT[d][t]['m5']
        return res
    return fn
def make_scoresmooth(w0,w1,w2, mw=0):  # 전체 score 평활 + mom5
    def fn(k):
        d=dts[k]; res={}
        for t in universe(k):
            if DAT[d][t]['gate']: continue
            sc0=DAT[d][t]['score']; sc1=val(k-1,t,'score'); sc2=val(k-2,t,'score')
            sc1=sc0 if sc1 is None else sc1; sc2=sc0 if sc2 is None else sc2
            res[t]=w0*sc0+w1*sc1+w2*sc2 + mw*DAT[d][t]['m5']
        return res
    return fn
P1=('20190102','20211231');P2=('20220101','20231231');P3=('20240101','20261231')
def show(name,fn):
    c,m,cal=run(fn); _,_,a=run(fn,P1); _,_,b=run(fn,P2); _,_,cc=run(fn,P3)
    print(f"  {name:28s}{cal:>7.2f}{a:>7.2f}{b:>7.2f}{cc:>7.2f}{m:>7.1f}")
print(f"  {'방식':28s}{'전체':>7s}{'강세':>7s}{'약세':>7s}{'최근':>7s}{'MDD':>7s}")
show('prod_wr (baseline)', f_prod_wr)
show('score평활 0.4/.35/.25', make_scoresmooth(0.4,0.35,0.25))
show('B:분리 slow평활+fast당일', make_split(1,0))
show('B:분리+mom5 mw0.03', make_split(1,0.03))
show('B:분리+mom5 mw0.05', make_split(1,0.05))

print("\n[A: wr/score 평활 축소 (당일 비중↑)]")
show('score 0.5/0.3/0.2', make_scoresmooth(0.5,0.3,0.2))
show('score 0.6/0.25/0.15', make_scoresmooth(0.6,0.25,0.15))
show('score 0.7/0.2/0.1', make_scoresmooth(0.7,0.2,0.1))
show('score 1.0 (당일=cr)', make_scoresmooth(1.0,0.0,0.0))

print("\n[E: 비대칭 mom — 상승만 당일반영(하락은 wr평활 유지)]")
def make_split_asym(mw):  # slow평활+fast당일 + mw*max(mom5,0)
    def fn(k):
        d=dts[k]; res={}
        for t in universe(k):
            if DAT[d][t]['gate']: continue
            s0=DAT[d][t]['slow']; s1=val(k-1,t,'slow'); s2=val(k-2,t,'slow')
            s1=s0 if s1 is None else s1; s2=s0 if s2 is None else s2
            res[t]=0.4*s0+0.35*s1+0.25*s2 + DAT[d][t]['fast'] + mw*max(DAT[d][t]['m5'],0.0)
        return res
    return fn
def make_wr_asym(mw):  # prod_wr baseline + 상승 mom5 부스트만
    def fn(k):
        d=dts[k]; res={}
        for t in universe(k):
            if DAT[d][t]['gate']: continue
            if CR[d].get(t,999)>50: continue
            res[t]=-(0.4*crv(k,t)+0.35*crv(k-1,t)+0.25*crv(k-2,t)) + mw*max(DAT[d][t]['m5'],0.0)
        return res
    return fn
show('E:분리+상승mom mw0.05', make_split_asym(0.05))
show('E:분리+상승mom mw0.1', make_split_asym(0.1))
show('E:prodwr+상승mom mw0.3', make_wr_asym(0.3))
show('E:prodwr+상승mom mw0.5', make_wr_asym(0.5))

print("\n[C: 비대칭 진입/이탈 — 진입 wr(안정), 이탈 cr(당일 급락 빠른손절)]")
def f_fast_exit(k):  # 진입=prod_wr, 이탈=당일 cr>6
    return f_prod_wr(k)  # placeholder; 별도 run 필요
def run_split_rule(entry_fn, exit_use_cr, sub=None):
    held=[];out=[];prev=None
    for k,d in enumerate(dts):
        ret=0.0
        if held and prev:
            rr=[parr[tdi[d],pcol[t]]/parr[tdi[prev],pcol[t]]-1 for t in held if t in pcol and parr[tdi[prev],pcol[t]]>0 and parr[tdi[d],pcol[t]]>0]
            ret=np.mean(rr) if rr else 0.0
        out.append((d,ret))
        if not reg.get(d,True): held=[]; prev=d; continue
        fs=entry_fn(k); ranked=sorted(fs.items(),key=lambda x:-x[1]); rank={t:i+1 for i,(t,_) in enumerate(ranked)}
        # 이탈: cr(당일순위) 사용 옵션
        if exit_use_cr:
            cr_today={t:CR[d].get(t,999) for t in held}
            held=[t for t in held if cr_today.get(t,999)<=6]
        else:
            held=[t for t in held if rank.get(t,999)<=6]
        for t,_ in ranked:
            if len(held)>=3: break
            if rank[t]<=3 and t not in held: held.append(t)
        prev=d
    a=np.array([r for dd,r in out if (not sub or sub[0]<=dd<=sub[1])])
    if len(a)<20: return 0,0,0
    eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return cagr,mdd,(cagr/abs(mdd) if mdd<0 else 0)
def show2(name,entry_fn,ecr):
    c,m,cal=run_split_rule(entry_fn,ecr); _,_,a=run_split_rule(entry_fn,ecr,P1); _,_,b=run_split_rule(entry_fn,ecr,P2); _,_,cc=run_split_rule(entry_fn,ecr,P3)
    print(f"  {name:28s}{cal:>7.2f}{a:>7.2f}{b:>7.2f}{cc:>7.2f}{m:>7.1f}")
show2('C:진입wr+이탈cr(빠른손절)', f_prod_wr, True)
show2('C:진입wr+이탈wr(baseline)', f_prod_wr, False)

print("\n[C 정밀: 이탈 cr 기준 스윕 + 회전율]")
def run_C(exit_cr_thresh, entry_wr=True, exclude=None, sub=None, count=False):
    held=[];out=[];prev=None;trades=0
    for k,d in enumerate(dts):
        ret=0.0
        if held and prev:
            rr=[parr[tdi[d],pcol[t]]/parr[tdi[prev],pcol[t]]-1 for t in held if t in pcol and parr[tdi[prev],pcol[t]]>0 and parr[tdi[d],pcol[t]]>0]
            ret=np.mean(rr) if rr else 0.0
        out.append((d,ret))
        if not reg.get(d,True):
            trades+=len(held); held=[]; prev=d; continue
        fs=f_prod_wr(k); ranked=sorted(fs.items(),key=lambda x:-x[1]); rank={t:i+1 for i,(t,_) in enumerate(ranked)}
        before=set(held)
        cr_today={t:CR[d].get(t,999) for t in held}
        held=[t for t in held if t!=exclude and cr_today.get(t,999)<=exit_cr_thresh]
        for t,_ in ranked:
            if len(held)>=3: break
            if t==exclude: continue
            if rank[t]<=3 and t not in held: held.append(t)
        trades+=len(set(held)-before)
        prev=d
    a=np.array([r for dd,r in out if (not sub or sub[0]<=dd<=sub[1])])
    if len(a)<20: return (0,0,0,trades)
    eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return (cagr,mdd,(cagr/abs(mdd) if mdd<0 else 0),trades)
print(f"  {'이탈기준':20s}{'전체':>7s}{'강세':>7s}{'약세':>7s}{'최근':>7s}{'MDD':>7s}{'거래수':>7s}")
bc,bm,bcal,btr=run_C(999)  # 이탈 안함 = 사실상 wr만? no, cr>999 never exit
for th in [4,5,6,8,999]:
    c,m,cal,tr=run_C(th); _,_,a,_=run_C(th,sub=P1); _,_,b,_=run_C(th,sub=P2); _,_,cc,_=run_C(th,sub=P3)
    lbl=f'cr>{th}' if th<999 else 'cr이탈안함(wr유지)'
    print(f"  {lbl:20s}{cal:>7.2f}{a:>7.2f}{b:>7.2f}{cc:>7.2f}{m:>7.1f}{tr:>7d}")
# wr 이탈(baseline) 거래수 비교
def run_wr_exit(sub=None):
    held=[];out=[];prev=None;trades=0
    for k,d in enumerate(dts):
        ret=0.0
        if held and prev:
            rr=[parr[tdi[d],pcol[t]]/parr[tdi[prev],pcol[t]]-1 for t in held if t in pcol and parr[tdi[prev],pcol[t]]>0 and parr[tdi[d],pcol[t]]>0]
            ret=np.mean(rr) if rr else 0.0
        out.append((d,ret))
        if not reg.get(d,True): trades+=len(held);held=[]; prev=d; continue
        fs=f_prod_wr(k); ranked=sorted(fs.items(),key=lambda x:-x[1]); rank={t:i+1 for i,(t,_) in enumerate(ranked)}
        before=set(held); held=[t for t in held if rank.get(t,999)<=6]
        for t,_ in ranked:
            if len(held)>=3: break
            if rank[t]<=3 and t not in held: held.append(t)
        trades+=len(set(held)-before); prev=d
    a=np.array([r for dd,r in out if (not sub or sub[0]<=dd<=sub[1])])
    eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return cagr/abs(mdd),trades
wcal,wtr=run_wr_exit()
print(f"  {'wr>6 이탈(baseline)':20s}{wcal:>7.2f}{'':>21s}{'':>7s}{wtr:>7d}")

print("\n[C 확정: 거래비용 반영 + LOWO + 인접]")
def run_C2(exit_mode, thresh=6, exclude=None, sub=None, cost=0.0):
    """exit_mode: 'cr' or 'wr'. cost=왕복 거래비용(%)"""
    held=[];out=[];prev=None
    for k,d in enumerate(dts):
        ret=0.0
        if held and prev:
            rr=[parr[tdi[d],pcol[t]]/parr[tdi[prev],pcol[t]]-1 for t in held if t in pcol and parr[tdi[prev],pcol[t]]>0 and parr[tdi[d],pcol[t]]>0]
            ret=np.mean(rr) if rr else 0.0
        if not reg.get(d,True):
            if held: ret-=cost/100*len(held)/max(len(held),1)  # 청산비용
            out.append((d,ret)); held=[]; prev=d; continue
        fs=f_prod_wr(k); ranked=sorted(fs.items(),key=lambda x:-x[1]); rank={t:i+1 for i,(t,_) in enumerate(ranked)}
        before=set(held)
        if exit_mode=='cr':
            crt={t:CR[d].get(t,999) for t in held}; held=[t for t in held if t!=exclude and crt.get(t,999)<=thresh]
        else:
            held=[t for t in held if t!=exclude and rank.get(t,999)<=thresh]
        for t,_ in ranked:
            if len(held)>=3: break
            if t==exclude: continue
            if rank[t]<=3 and t not in held: held.append(t)
        nchg=len(set(held)^before)  # 진입+이탈 종목수
        ret-=cost/100*nchg/3.0  # 회전 비용(슬롯당)
        out.append((d,ret)); prev=d
    a=np.array([r for dd,r in out if (not sub or sub[0]<=dd<=sub[1])])
    if len(a)<20: return 0,0,0
    eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return cagr,mdd,(cagr/abs(mdd) if mdd<0 else 0)
print("  [왕복 거래비용 0.3% 반영]")
for mode,th in [('wr',6),('cr',6)]:
    c,m,cal=run_C2(mode,th,cost=0.3); _,_,a=run_C2(mode,th,sub=P1,cost=0.3); _,_,b=run_C2(mode,th,sub=P2,cost=0.3); _,_,cc=run_C2(mode,th,sub=P3,cost=0.3)
    print(f"  {mode}>{th} 비용반영: 전체 {cal:.2f} 강세 {a:.2f} 약세 {b:.2f} 최근 {cc:.2f} MDD {m:.1f}")
print("\n  [LOWO — cr>6 vs wr>6, 슈퍼위너 제외]")
for ex,nm in [('000660','SK하이닉스'),('080220','제주반도체'),('089970','브이엠'),('042700','한미반도체'),('039030','이오테크닉스')]:
    _,_,cc=run_C2('cr',6,exclude=ex); _,_,ww=run_C2('wr',6,exclude=ex)
    print(f"  −{nm:12s} cr>6 {cc:>6.2f}  wr>6 {ww:>6.2f}  Δ{cc-ww:>+6.2f}")
