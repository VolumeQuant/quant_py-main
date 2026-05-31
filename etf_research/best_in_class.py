"""동일지수 best-in-class 엔진 (오프라인, _cache/ohlcv_liquid 사용).
핵심 통찰: 같은 지수 추종 ETF끼리 NAV 총수익 차이 ≈ 실부담비용+추적오차+펀드내세금 차이.
→ KOFIA 보수데이터 없이도 NAV총수익(높을수록 저드래그) + 괴리율변동(낮을수록 체결우수) + 유동성으로 랭킹.
실행: python etf_research/best_in_class.py
"""
import sys, json
from pathlib import Path
import pandas as pd, numpy as np
sys.stdout.reconfigure(encoding='utf-8')
C = Path(__file__).parent / '_cache'
names = json.loads((C/'names.json').read_text(encoding='utf-8'))
oh = pd.read_parquet(C/'ohlcv_liquid.parquet')
oh['etf'] = oh['etf'].astype(str)

# 오염 제거: 동일지수 '순수' 추종만 (레버리지/인버스/커버드콜/채권혼합/환헤지/TR 등 변형 제외)
CONTAM = ['레버리지','인버스','2X','2x','곱버스','커버드콜','데일리','채권혼합','채권','혼합','TR','(H)','합성','타겟','OTM','위클리']
def pure(n): return not any(k in n for k in CONTAM)
CLUSTERS = {
    '미국 S&P500':   lambda n: ('S&P500' in n or 'S&P 500' in n) and pure(n),
    '미국 나스닥100': lambda n: '나스닥100' in n and pure(n),
    '코스피200':     lambda n: (n.split()[-1]=='200' if n.split() else False) and pure(n),  # 끝이 정확히 '200'(섹터 200 건설 등 제외)
    '미국 필라델피아반도체': lambda n: ('필라델피아반도체' in n) and pure(n),
    '2차전지':       lambda n: '2차전지' in n and pure(n),
    '미국 빅테크/M7': lambda n: any(k in n for k in ['빅테크','M7','매그니피센트']) and pure(n),
    '골드/금':       lambda n: ('골드' in n or 'KRX금' in n) and pure(n),
}

# 공통 윈도우(최근 120 거래일)로 NAV총수익 비교 = 공정 (신규상장 부분기간 왜곡 제거)
all_dates = sorted(oh['date'].unique())
WIN = all_dates[-120:] if len(all_dates) >= 120 else all_dates
WIN0 = WIN[0]
def metrics(etf):
    d = oh[(oh.etf==etf) & (oh.date>=WIN0)].sort_values('date')
    d = d[d.nav>0]
    if len(d) < 110: return None  # 공통 윈도우 거의 풀로 존재해야 (신규상장 제외)
    nret = d['nav'].iloc[-1]/d['nav'].iloc[0] - 1
    dev = (d['close']/d['nav']-1)
    return {'nav_ret': nret*100, 'dev_std': dev.std()*100, 'dev_mean': dev.mean()*100,
            'liq': d['value'].tail(20).mean(), 'days': len(d)}
print(f"(공통 윈도우: 최근 {len(WIN)}거래일, {WIN0}~{WIN[-1]})", flush=True)

print(f"=== 동일지수 best-in-class (NAV총수익=저드래그 / 괴리율변동=체결 / 유동성) ===", flush=True)
for label, fn in CLUSTERS.items():
    members = [t for t in oh.etf.unique() if fn(names.get(t,''))]
    rows = []
    for t in members:
        m = metrics(t)
        if m: rows.append({'etf': t, 'name': names.get(t,t), **m})
    if len(rows) < 2: continue
    df = pd.DataFrame(rows)
    # 랭크: nav_ret↑, dev_std↓, liq↑
    df['score'] = (df.nav_ret.rank() + (-df.dev_std).rank() + df.liq.rank())
    df = df.sort_values('score', ascending=False)
    print(f"\n■ {label}  ({len(df)}개)", flush=True)
    print(f"  {'ETF':<28}{'NAV수익':>8}{'괴리변동':>8}{'평균거래대금':>12}", flush=True)
    for r in df.itertuples():
        star = ' ★best' if r.Index==df.index[0] else ''
        print(f"  {r.name[:26]:<28}{r.nav_ret:>+7.1f}%{r.dev_std:>7.2f}%{r.liq/1e8:>10.0f}억{star}", flush=True)
print("\n(주: NAV총수익 차이가 곧 비용+추적오차 차이. KOFIA 보수 결합 시 정밀도↑)", flush=True)
