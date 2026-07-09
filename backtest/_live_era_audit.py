# -*- coding: utf-8 -*-
"""라이브 시대(2026-02~) 전수 감사 — web_data(실발송 픽) 기반.
①실발송 픽 추종 수익(메시지 팔로워 수익) vs KOSPI ②SK 의존도(ex-SK) ③픽 변경 빈도/공백일
④거래일 커버리지(결번 감사) ⑤최악의 날들. BT가 아니라 '실제 나간 신호'의 원장."""
import sys, io, os, glob, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd

R = 'C:/dev/claude-code/quant_py-main'
px = pd.read_parquet(sorted(glob.glob(R + '/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0, np.nan)
k = pd.read_parquet(R + '/data_cache/kospi_yf.parquet').iloc[:, 0].dropna()

picks_by_day = {}
for f in sorted(glob.glob(R + '/state/web_data_*.json')):
    dt = os.path.basename(f)[9:17]
    try:
        d = json.load(open(f, encoding='utf-8'))
        picks_by_day[dt] = [p['ticker'] for p in d.get('picks', [])]
    except Exception:
        continue
days = sorted(picks_by_day)
print(f"실발송 원장: {days[0]} ~ {days[-1]}, {len(days)}일")

# 거래일 커버리지 (결번 감사): px 인덱스 기준 거래일 중 web_data 없는 날
trad = [d.strftime('%Y%m%d') for d in px.index if days[0] <= d.strftime('%Y%m%d') <= days[-1]]
missing = [d for d in trad if d not in picks_by_day]
print(f"거래일 {len(trad)}일 중 web_data 결번 {len(missing)}일: {missing[:10]}")

# 픽 추종 수익 (전일 픽 보유 → 오늘 수익, 동일가중; 픽 없으면 현금)
def follow(exclude=None):
    rets = []
    for i in range(1, len(days)):
        d0, d1 = days[i - 1], days[i]
        hold = [t for t in picks_by_day[d0] if t != exclude]
        rr = []
        for t in hold:
            if t not in px.columns: continue
            try:
                p0 = px[t].loc[:pd.Timestamp(d0)].dropna().iloc[-1]
                p1 = px[t].loc[:pd.Timestamp(d1)].dropna().iloc[-1]
                if p0 > 0: rr.append(p1 / p0 - 1)
            except Exception:
                continue
        rets.append((d1, np.mean(rr) if rr else 0.0, len(hold)))
    return pd.DataFrame(rets, columns=['d', 'ret', 'n'])

full = follow()
exsk = follow(exclude='000660')
def stats(df):
    eq = (1 + df['ret']).cumprod()
    mdd = (eq / eq.cummax() - 1).min() * 100
    return (eq.iloc[-1] - 1) * 100, mdd
fr, fm = stats(full); er, em = stats(exsk)
kk = k[(k.index >= days[0]) & (k.index <= days[-1])]
kr = (kk.iloc[-1] / kk.iloc[0] - 1) * 100
print(f"\n===== 실발송 픽 추종 수익 ({days[0]}~{days[-1]}) =====")
print(f"  픽 추종(동일가중): {fr:+.1f}% (MDD {fm:.1f}%)")
print(f"  ★SK 제외 시:      {er:+.1f}% (MDD {em:.1f}%)")
print(f"  KOSPI 동기간:      {kr:+.1f}%")
print(f"  → SK 단일 기여도: {fr - er:+.1f}%p")

# 픽 구성 통계
allp = [t for d in days for t in picks_by_day[d]]
from collections import Counter
cnt = Counter(allp)
try:
    NM = json.load(open(R + '/data_cache/ticker_names_cache.json', encoding='utf-8'))
except Exception:
    NM = {}
print(f"\n===== 픽 등장 빈도 (총 {len(days)}일) =====")
for t, c in cnt.most_common(10):
    n = NM.get(t, t); n = n if isinstance(n, str) else t
    print(f"  {n:12s}: {c}일 ({c/len(days)*100:.0f}%)")
np_days = sum(1 for d in days if not picks_by_day[d])
n_counts = Counter(len(picks_by_day[d]) for d in days)
print(f"\n픽 개수 분포: {dict(sorted(n_counts.items()))} (0개={np_days}일)")
chg = sum(1 for i in range(1, len(days)) if set(picks_by_day[days[i]]) != set(picks_by_day[days[i-1]]))
print(f"픽 구성 변경일: {chg}/{len(days)-1}일 ({chg/(len(days)-1)*100:.0f}%)")

# 최악의 날 top5
w = full.nsmallest(5, 'ret')
print("\n===== 최악의 날 5 =====")
for _, r in w.iterrows():
    print(f"  {r['d']}: {r['ret']*100:+.1f}% (보유 {int(r['n'])}종목)")
