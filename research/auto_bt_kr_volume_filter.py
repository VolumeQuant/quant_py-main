"""KR production 거래대금(주도주) universe 필터 검증 — US v114 $1B 필터의 KR 독립 검증.
bt_kp_validate.py 하니스 재사용: ranking factor z 재가중 → 거래대금 threshold 필터 → regime cross → 시뮬.
baseline(현 production, 이미 15~50억 필터) 대비 더 엄격한 거래대금 threshold 스윕.
PIT 거래대금 = 각 BT date의 nearest market_cap_ALL_<=date 파일 거래대금(volume×price). future leak 없음.
실행: python research/auto_bt_kr_volume_filter.py
"""
import sys, json, glob, re, bisect
from pathlib import Path
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(r'C:\dev\claude-code\quant_py-main'); STATE = ROOT/'state'; DATA = ROOT/'data_cache'
PENALTY=50; TOP_N=20; W=(0.15,0.0,0.65,0.20)

ohlcv = pd.read_parquet(sorted(DATA.glob('all_ohlcv_2017*.parquet'))[-1]).replace(0,np.nan)
kospi = pd.read_parquet(str(DATA/'kospi_yf.parquet')).iloc[:,0].sort_index()

# ── PIT 거래대금 맵 (nearest market_cap_ALL_<=date, 억 단위) ──
mc_files = []
for fp in DATA.glob('market_cap_ALL_*.parquet'):
    m = re.search(r'(\d{8})', fp.name)
    if m: mc_files.append((m.group(1), fp))
mc_files.sort()
mc_dates = [d for d,_ in mc_files]
_mc_cache = {}
def _load_mc(path):
    if path not in _mc_cache:
        df = pd.read_parquet(path)
        # '거래대금' 컬럼을 이름으로 선택 (파일별 컬럼수 5/6 상이) — 없으면 위치(4번째) 폴백
        col = next((c for c in df.columns if '거래대금' in str(c)), None)
        if col is None:
            col = df.columns[3] if len(df.columns) >= 4 else df.columns[-1]
        _mc_cache[path] = (df[col]/1e8).to_dict()  # ticker -> 거래대금(억)
    return _mc_cache[path]
def vol_map(d):
    """date d 이하 가장 가까운 market_cap 파일의 거래대금(억) dict."""
    i = bisect.bisect_right(mc_dates, d) - 1
    if i < 0: return {}
    return _load_mc(mc_files[i][1])

def load_factors(d):
    fp=STATE/f'ranking_{d}.json'
    if not fp.exists(): return {}
    data=json.load(open(fp,encoding='utf-8'))
    return {str(r['ticker']).zfill(6):(r.get('value_s',0) or 0,r.get('quality_s',0) or 0,
            r.get('growth_s',0) or 0,r.get('momentum_s',0) or 0) for r in data['rankings']}

dates=sorted([fp.stem.replace('ranking_','') for fp in STATE.glob('ranking_*.json')
              if fp.stem.replace('ranking_','').isdigit() and len(fp.stem.replace('ranking_',''))==8
              and '20180702'<=fp.stem.replace('ranking_','')<='20260529'])
print(f'BT 대상 {len(dates)}일 ({dates[0]}~{dates[-1]})', flush=True)
fac={d:load_factors(d) for d in dates}
vol={d:vol_map(d) for d in dates}
print(f'거래대금 맵 로드 완료 (market_cap 파일 {len(mc_files)}개)', flush=True)

def cross(ds):
    sma=kospi.rolling(20).mean(); lma=kospi.rolling(80).mean(); reg={};md=False;stk=0;ss=None
    for d in ds:
        ts=pd.Timestamp(d);sv=sma.get(ts);lv=lma.get(ts)
        if sv is None or pd.isna(sv) or pd.isna(lv): reg[d]=md;continue
        s=sv>lv
        if s==ss: stk+=1
        else: stk=1;ss=s
        if stk>=5 and md!=s: md=s
        reg[d]=md
    return reg

def gp(d,tk):
    ts=pd.Timestamp(d)
    if ts not in ohlcv.index:
        idx=ohlcv.index.searchsorted(ts)
        if idx>=len(ohlcv): return None
        ts=ohlcv.index[idx]
    if tk not in ohlcv.columns: return None
    v=ohlcv.loc[ts,tk]; return v if pd.notna(v) and v>0 else None

def cr_map(d,exclude,min_val):
    """거래대금 ≥ min_val(억) 필터 + 가중치 → composite_rank dict. min_val=0이면 baseline(현 production)."""
    f=fac.get(d,{}); vm=vol.get(d,{}); sc=[]
    for t,(vs,qs,gs,ms) in f.items():
        if t in exclude: continue
        if min_val>0 and vm.get(t,0) < min_val: continue
        sc.append((t, W[0]*vs+W[1]*qs+W[2]*gs+W[3]*ms))
    sc.sort(key=lambda x:-x[1])
    return {t:i+1 for i,(t,_) in enumerate(sc)}

def run_bt(ds,regime,min_val,slots=3,eb=3,xb=4,exclude=set(),track=False):
    pf={};eq=1.0;eh={};contrib={}
    crc={d:cr_map(d,exclude,min_val) for d in ds}
    for i,d in enumerate(ds):
        ib=regime.get(d,True)
        if i>=1 and pf:
            rets=[]
            for tk in list(pf):
                pp=gp(ds[i-1],tk);cp=gp(d,tk)
                if pp and cp:
                    r=cp/pp-1; rets.append(r)
                    if track: contrib[tk]=contrib.get(tk,0)+r*(1/slots)
            if rets: eq*=(1+np.mean(rets)*len(pf)/slots)
        eh[d]=eq
        if i>=1 and regime.get(ds[i-1],True)!=ib: pf.clear()
        if not ib: continue
        c0=crc.get(d,{});c1=crc.get(ds[i-1],{}) if i>=1 else {};c2=crc.get(ds[i-2],{}) if i>=2 else {}
        t1={t:c for t,c in c1.items() if c<=TOP_N};t2={t:c for t,c in c2.items() if c<=TOP_N}
        wr={t:c0[t]*0.4+t1.get(t,PENALTY)*0.35+t2.get(t,PENALTY)*0.25 for t in c0}
        for tk in list(pf):
            if wr.get(tk,999)>xb: del pf[tk]
        for tk,_ in sorted(wr.items(),key=lambda x:x[1])[:eb]:
            if tk in pf: continue
            if len(pf)>=slots: break
            if gp(d,tk): pf[tk]=1
    ea=np.array(list(eh.values()))
    if len(ea)<50: return (0,0,0,{},contrib)
    cagr=(ea[-1]**(252/len(ea))-1)*100
    pk=np.maximum.accumulate(ea);mdd=-((ea-pk)/pk).min()*100
    cal=cagr/mdd if mdd>0 else 0
    return (cal,cagr,mdd,eh,contrib)

isd=[d for d in dates if d<='20221231']; oosd=[d for d in dates if d>='20230102']
reg=cross(dates); regi=cross(isd); rego=cross(oosd)

# 거래대금 threshold 스윕 (억). 0=baseline(현 production). p80=33 p90=129 기준.
THRESHOLDS = [0, 50, 100, 200, 300, 500]
print(f'\n{"필터(억)":>10} | {"Cal":>5} {"CAGR":>5} {"MDD":>5} | {"IS":>5} {"OOS":>5} | {"WFmin":>5} | {"LOO3":>5} | 평균픽수', flush=True)
print('-'*78, flush=True)
base_cal=None
for mv in THRESHOLDS:
    cal,cagr,mdd,eh,contrib=run_bt(dates,reg,mv,track=True)
    ic,_,_,_,_=run_bt(isd,regi,mv); oc,_,_,_,_=run_bt(oosd,rego,mv)
    wf=[]
    for st,ed in [('20180702','20191231'),('20200101','20211231'),('20220101','20231231'),('20240101','20260529')]:
        sub=[d for d in dates if st<=d<=ed]
        if len(sub)>=50:
            c,_,_,_,_=run_bt(sub,cross(sub),mv); wf.append(c)
    top=sorted(contrib.items(),key=lambda x:-x[1])[:3]; ex=set(t for t,_ in top)
    loo3,_,_,_,_=run_bt(dates,reg,mv,exclude=ex)
    # 평균 픽 universe 크기
    avgn=np.mean([len(cr_map(d,set(),mv)) for d in dates[::50]])
    lbl='baseline' if mv==0 else f'≥{mv}억'
    d_cal = '' if base_cal is None else f' (Δ{cal-base_cal:+.2f})'
    if mv==0: base_cal=cal
    print(f'{lbl:>10} | {cal:5.2f} {cagr:5.0f} {mdd:5.0f} | {ic:5.2f} {oc:5.2f} | {min(wf):5.2f} | {loo3:5.2f} | {avgn:6.0f}{d_cal}', flush=True)

print('\n채택조건: Cal baseline 우월 + WFmin 양호 + IS/OOS 둘 다 우월 + MDD악화<5p + LOO robust.', flush=True)
print('US와 달리 KR은 소형주 폭발이 알파(KP200 narrowing 거부 전례) → 필터가 해로우면 baseline 유지.', flush=True)
