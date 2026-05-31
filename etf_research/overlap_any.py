"""ETF 중복도/분산 분석 — 임의 ETF 조합 (사용자 입력형 기능 프로토타입).
'여러 ETF를 담았는데 사실 같은 것 아닌가?' = 증권사/토스가 안 주는 핵심 차별화.
입력 ETF 묶음 → 쌍별 중복% + 합성 포트 종목 쏠림 + 유효 분산(1/HHI) 리포트.
현재는 _cache/holdings.parquet(액티브 ETF)로 데모. 임의 ETF 일반화 시 PDF 라이브 fetch만 추가.
실행: python etf_research/overlap_any.py [TICKER1 TICKER2 ...]
"""
import sys, json
from pathlib import Path
import pandas as pd, numpy as np
sys.stdout.reconfigure(encoding='utf-8')
C = Path(__file__).parent / '_cache'
names = json.loads((C/'names.json').read_text(encoding='utf-8'))
h = pd.read_parquet(C/'holdings.parquet'); h['stock']=h['stock'].astype(str).str.zfill(6)
latest = sorted(h['snap'].unique())[-1]
hl = h[h.snap==latest]
sname = hl.drop_duplicates('stock').set_index('stock')['sname'].to_dict()

def hold(etf):
    g = hl[hl.etf==etf]
    w = g.set_index('stock')['weight']
    w = w[~w.index.duplicated()]
    return w[w > 0]  # 0비중(외국주식/현금 등) 제외

def pair_overlap(a, b):
    """가중 중복% = sum_i min(w_a_i, w_b_i) (정규화 후)."""
    wa, wb = hold(a)/hold(a).sum(), hold(b)/hold(b).sum()
    common = wa.index.intersection(wb.index)
    return sum(min(wa[i], wb[i]) for i in common) * 100

def analyze(tickers, ew=None):
    tickers = [t for t in tickers if not hl[hl.etf==t].empty]
    if len(tickers) < 2:
        print('유효 ETF 2개 이상 필요 (현재 캐시=액티브 ETF만)'); return
    print(f"=== 중복도/분산 리포트 ({latest}) ===")
    print('대상:', ' / '.join(f"{names.get(t,t)}" for t in tickers))
    print(f"\n■ 쌍별 가중 중복도")
    for i in range(len(tickers)):
        for j in range(i+1, len(tickers)):
            print(f"  {pair_overlap(tickers[i],tickers[j]):5.1f}%  {names.get(tickers[i],tickers[i])[:18]} ↔ {names.get(tickers[j],tickers[j])[:18]}")
    # 합성 포트 (ETF 동일가중) → 종목 노출 합산
    ew = ew or [1/len(tickers)]*len(tickers)
    agg = {}
    for t, w_etf in zip(tickers, ew):
        wt = hold(t)/hold(t).sum()
        for s, w in wt.items(): agg[s] = agg.get(s,0) + w*w_etf
    agg = pd.Series(agg).sort_values(ascending=False)
    hhi = (agg**2).sum(); eff_n = 1/hhi
    print(f"\n■ 합성 포트(ETF 동일가중) 종목 쏠림 Top8")
    for s, w in agg.head(8).items():
        print(f"  {sname.get(s,s)[:16]:<18} {w*100:5.2f}%")
    print(f"\n■ 분산 진단: 합성 보유종목 {len(agg)}개, **유효 분산종목수(1/HHI) = {eff_n:.0f}개**")
    print(f"  → 명목 {len(agg)}개지만 쏠림으로 실효 {eff_n:.0f}개 수준. 상위3 비중 {agg.head(3).sum()*100:.0f}%")
    if eff_n < len(agg)*0.3:
        print("  ⚠️ 분산 착시: ETF 여러 개지만 같은 대형주에 집중 = 분산 효과 작음")

if __name__ == '__main__':
    args = [a.zfill(6) for a in sys.argv[1:]]
    if not args:
        # 데모: '서로 달라 보이지만 사실 거의 같은' KR 코스피형 액티브 (중복도 시연)
        KW = ['200액티브','코스피액티브','코리아그로스액티브','다이나믹퀀트액티브']
        args = []
        for t, n in names.items():
            if any(k in n for k in KW) and not hl[hl.etf==t].empty and hold(t).sum() > 50:
                args.append(t)
            if len(args) >= 4: break
        print(f"(데모: KR 코스피형 액티브 {len(args)}개 = '달라 보이는데 같은가?' 시연. 실사용: python overlap_any.py 069500 ...)\n")
    analyze(args)
