# -*- coding: utf-8 -*-
"""거시 3축(경기/물가/금리) 피처 빌더 + 룩어헤드 방지 lag. 다른 스크립트서 import.
저장된 macro_raw.pkl 로드 → 팩터 백테스트 날짜에 as-of 정렬."""
import pickle, pandas as pd, numpy as np
SCR=r"C:\Users\user\AppData\Local\Temp\claude\C--dev-claude-code-quant-py-main\2603077c-999d-4cc4-9297-dedf6ff9a203\scratchpad"
_raw=pickle.load(open(SCR+r"\macro_raw.pkl","rb"))

def _asof(series, ts, lag_days):
    """ts-lag_days 시점에 실제로 알 수 있던 마지막 값 (룩어헤드 방지)."""
    cut=ts - pd.Timedelta(days=lag_days)
    s=series[series.index<=cut]
    return float(s.iloc[-1]) if len(s) else np.nan

# 발표지연(일): 월간지표는 익월 발표 → 35일, 일간(시장)은 실시간(거래일 정렬만 1일)
LAG={'cpi':35,'base_rate':2,'ktb3':1,'ktb10':1,'usdkrw':1,'us10y':1,'curve':1,'us_mfg':40}

def build(dates):
    """dates: 'YYYYMMDD' 리스트 → 거시 피처 DataFrame (index=date str)."""
    idx=[pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]) for d in dates]
    cpi=_raw['cpi']; br=_raw['base_rate']; k3=_raw['ktb3']; k10=_raw['ktb10']
    fx=_raw['usdkrw']; us10=_raw['us10y']; cv=_raw['curve']; mfg=_raw['us_mfg']
    rows=[]
    for d,ts in zip(dates,idx):
        # 물가
        cpi_now=_asof(cpi,ts,LAG['cpi']); cpi_12=_asof(cpi,ts-pd.Timedelta(days=365),LAG['cpi'])
        cpi_yoy=(cpi_now/cpi_12-1)*100 if cpi_12 else np.nan
        cpi_6=_asof(cpi,ts-pd.Timedelta(days=182),LAG['cpi']); cpi_18=_asof(cpi,ts-pd.Timedelta(days=182+365),LAG['cpi'])
        cpi_yoy_6mago=(cpi_6/cpi_18-1)*100 if cpi_18 else np.nan
        infl_chg=cpi_yoy-cpi_yoy_6mago  # 인플레 가속(+)/둔화(-)
        # 금리
        rate=_asof(br,ts,LAG['base_rate']); rate_6=_asof(br,ts-pd.Timedelta(days=182),LAG['base_rate'])
        rate_dir=rate-rate_6  # 인상(+)/인하(-)
        ktb3=_asof(k3,ts,1); ktb3_60=_asof(k3,ts-pd.Timedelta(days=90),1)
        ktb3_dir=ktb3-ktb3_60  # 시장금리 방향
        kr_term=_asof(k10,ts,1)-ktb3  # 한국 장단기 스프레드(가팔라짐=경기기대)
        # 경기/위험
        curve=_asof(cv,ts,1)  # 미 10-2 (역전<0=침체우려)
        fxnow=_asof(fx,ts,1); fx60=_asof(fx,ts-pd.Timedelta(days=90),1)
        fx_mom=(fxnow/fx60-1)*100 if fx60 else np.nan  # 원화약세(+)=위험회피
        mfgnow=_asof(mfg,ts,LAG['us_mfg']); mfg12=_asof(mfg,ts-pd.Timedelta(days=365),LAG['us_mfg'])
        mfg_yoy=(mfgnow/mfg12-1)*100 if mfg12 else np.nan  # 미 제조업 경기
        rows.append(dict(date=d,cpi_yoy=cpi_yoy,infl_chg=infl_chg,rate=rate,rate_dir=rate_dir,
                         ktb3=ktb3,ktb3_dir=ktb3_dir,kr_term=kr_term,curve=curve,fx_mom=fx_mom,mfg_yoy=mfg_yoy))
    return pd.DataFrame(rows).set_index('date')

if __name__=='__main__':
    import sys,io,glob,os
    sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
    ds=sorted(os.path.basename(f)[8:16] for f in glob.glob('C:/dev/state/ranking_*.json'))
    ds=[d for d in ds if d.isdigit() and len(d)==8 and d>='20190102']
    df=build(ds)
    print("거시 피처 (룩어헤드 lag 적용), 2019-2026 정렬\n")
    print(df.describe().round(2).T[['min','25%','50%','75%','max']])
    print("\n연도별 평균:")
    df['yr']=[d[:4] for d in df.index]
    print(df.groupby('yr').mean().round(2)[['cpi_yoy','infl_chg','rate','rate_dir','ktb3_dir','kr_term','curve','fx_mom','mfg_yoy']])
