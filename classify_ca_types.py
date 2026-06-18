# -*- coding: utf-8 -*-
"""down-CA 이벤트를 DART 공시로 무상증자/유상증자/분할/병합/감자 분류 → 타입별 권리락후 수익 +
무상증자 제외 ca_events 생성. "무상증자 페널티 합당한가" 검증용."""
import sys, io, json, glob, time
sys.path.insert(0, 'C:/dev'); sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
import OpenDartReader
from config import DART_API_KEYS

dart = OpenDartReader(DART_API_KEYS[0])
ca = json.load(open('C:/dev/data_cache/ca_events.json', encoding='utf-8'))['ca_by_ticker']
px = pd.read_parquet(sorted(glob.glob('C:/dev/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0, np.nan)
kc = pd.read_parquet('C:/dev/data_cache/kospi_yf.parquet').iloc[:, 0]

def ctype(t):
    if '무상증자' in t: return '무상증자'
    if '유상증자' in t: return '유상증자'
    if '분할' in t: return '분할'
    if '병합' in t: return '병합'
    if '감자' in t: return '감자'
    return None

# 1. 종목별 CA공시 수집
print(f"[분류] {len(ca)}종목 DART 조회 시작", flush=True)
ca_disc = {}  # tk -> [(date, type)]
fail = 0
for i, tk in enumerate(ca):
    try:
        df = dart.list(tk, start='2017-01-01', end='2026-06-30')
        lst = []
        if df is not None and len(df):
            for _, r in df.iterrows():
                ty = ctype(str(r.get('report_nm', '')))
                if ty: lst.append((str(r.get('rcept_dt')), ty))
        ca_disc[tk] = lst
    except Exception:
        fail += 1; ca_disc[tk] = []
    if (i + 1) % 100 == 0: print(f"  {i+1}/{len(ca)} (실패 {fail})", flush=True)
    time.sleep(0.15)
print(f"[분류] 완료, DART 미발견 {fail}종목", flush=True)

# 2. 각 gap을 가장 가까운 직전 CA공시로 분류 (window: gap-90d ~ gap+5d)
events = []  # (tk, gap, type)
for tk, gaps in ca.items():
    disc = ca_disc.get(tk, [])
    for g in gaps:
        gd = pd.Timestamp(g)
        cand = [(d, ty) for d, ty in disc if d and pd.notna(pd.Timestamp(d))
                and (gd - pd.Timedelta(days=90)) <= pd.Timestamp(d) <= (gd + pd.Timedelta(days=5))]
        if cand:
            cand.sort(key=lambda x: abs((pd.Timestamp(x[0]) - gd).days))
            events.append((tk, g, cand[0][1]))
        else:
            events.append((tk, g, '미상'))

from collections import Counter
cnt = Counter(t for _, _, t in events)
print(f"\n[타입 분포] {dict(cnt)}")

# 3. 타입별 권리락 후 수익 (수정주가, vs KOSPI)
didx = {d.strftime('%Y%m%d'): i for i, d in enumerate(px.index)}
kidx = {d.strftime('%Y%m%d'): i for i, d in enumerate(kc.index)}
def fwd(tk, g, k):
    ci = px.columns.get_loc(tk) if tk in px.columns else None
    i0 = didx.get(g)
    if ci is None or i0 is None: return None
    sub = px.iloc[i0:i0+k+1, ci].dropna()
    if len(sub) < 2: return None
    return sub.iloc[-1] / sub.iloc[0] - 1
def kfwd(g, k):
    ts = pd.Timestamp(g)
    pos = kc.index.searchsorted(ts)
    if pos + k >= len(kc): return None
    return kc.iloc[pos+k] / kc.iloc[pos] - 1
print(f"\n[타입별 권리락후 20일 수익 (수정주가 / KOSPI대비 알파)]")
for ty in ['무상증자', '유상증자', '분할', '병합', '감자', '미상']:
    rs = []; al = []
    for tk, g, t in events:
        if t != ty: continue
        f = fwd(tk, g, 20); kf = kfwd(g, 20)
        if f is not None and kf is not None: rs.append(f); al.append(f - kf)
    if rs:
        print(f"  {ty:<6} n={len(rs):>4}  fwd20d {np.mean(rs)*100:+.2f}%  알파 {np.mean(al)*100:+.2f}%p  승률 {(np.array(rs)>0).mean()*100:.0f}%")

# 4. 무상증자 제외 ca_events 생성 (페널티에서 무상증자 빼기)
ca_no무상 = {}
for tk, g, t in events:
    if t == '무상증자': continue
    ca_no무상.setdefault(tk, []).append(g)
json.dump({'ca_by_ticker': ca_no무상, 'method': 'down_gap_excl_무상증자'},
          open('C:/dev/data_cache/ca_events_no무상.json', 'w', encoding='utf-8'), ensure_ascii=True)
json.dump({'events': events}, open('C:/dev/data_cache/ca_classified.json', 'w', encoding='utf-8'), ensure_ascii=True)
print(f"\n[저장] ca_events_no무상.json ({len(ca_no무상)}종목), ca_classified.json")
print("→ 다음: 무상증자 제외 페널티로 재BT (Calmar 비교)")
