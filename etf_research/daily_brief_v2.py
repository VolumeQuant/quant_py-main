"""ETF 스마트머니 데일리 v2 — 전부 _cache 기반 오프라인 (라이브 콜 0). 빠르고 재현가능.
v1 대비: A surge비율+레버리지제외 / D cross-ETF 합의 / crowding 추가.
실행: python etf_research/daily_brief_v2.py [--send]
"""
import sys, json
from pathlib import Path
import pandas as pd, numpy as np
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
C = Path(__file__).parent / '_cache'
SEND = '--send' in sys.argv

names = json.loads((C/'names.json').read_text(encoding='utf-8'))
def nm(t): return names.get(t, t)
LEV = ['레버리지','인버스','2X','2x','곱버스']
def is_lev(t): return any(k in nm(t) for k in LEV)
# 괴리율 validated 알림용: 해외기초/합성/원자재 제외(시차 구조적 괴리=함정, 검증서 반등 약함)
EXCL_OS = LEV + ['합성','(H)','미국','차이나','중국','인도','베트남','일본','유럽','글로벌','월드','선진국','신흥',
                 '원유','WTI','금','은','구리','달러','엔','해외','나스닥','S&P','필라델피아','항셍','니케이']
def domestic(t): return not any(k in nm(t) for k in EXCL_OS)

oh = pd.read_parquet(C/'ohlcv_liquid.parquet')
oh['stock'] = oh['etf'].astype(str)
BASE = oh['date'].max()
ohb = oh[oh.date==BASE].set_index('etf')

# === A: surge (당일 거래대금 / 최근20일 평균) + 레버리지 제외 ===
piv = oh.pivot_table(index='date', columns='etf', values='value').sort_index()
avg20 = piv.rolling(20).mean()
surge = (piv.loc[BASE] / avg20.loc[BASE]).dropna()
surge = surge[[t for t in surge.index if not is_lev(t)]]
ret = oh.pivot_table(index='date', columns='etf', values='close').sort_index()
ret1 = (ret.loc[BASE]/ret.iloc[-2]-1).dropna()
top_surge = surge.sort_values(ascending=False).head(6)

# === E: 괴리율 (종가/NAV-1) ===
ohb2 = ohb[ohb.nav>0].copy(); ohb2['dev'] = ohb2['close']/ohb2['nav']-1
dev = ohb2['dev'].sort_values()
trap = pd.concat([dev.head(3), dev.tail(3)])
# 괴리율 validated 기회: 국내기초 + 거래대금≥20억 + 음괴리 ≤-3% (검증 edge)
opp = ohb2[(ohb2['dev']<=-0.03) & (ohb2['value']>=2e9) & (pd.Series(ohb2.index, index=ohb2.index).map(domestic))].sort_values('dev')

# === B: 투자자 순매수 (레버리지 제외) ===
inv = pd.read_parquet(C/'investor.parquet'); inv['etf']=inv['etf'].astype(str)
inv = inv[~inv['etf'].map(is_lev)]
foreign = inv.set_index('etf')['foreign'].sort_values(ascending=False)
inst = inv.set_index('etf')['inst'].sort_values(ascending=False)

# === D: cross-ETF 합의 신규편입 (최신 스냅 전이) ===
h = pd.read_parquet(C/'holdings.parquet'); h['stock']=h['stock'].astype(str).str.zfill(6)
snaps = sorted(h['snap'].unique())
sp, sc = snaps[-2], snaps[-1]
prev_sets = h[h.snap==sp].groupby('etf')['stock'].apply(set).to_dict()
newc = {}
for etf, g in h[h.snap==sc].groupby('etf'):
    pv = prev_sets.get(etf, set())
    if not pv: continue
    for stk in set(g['stock'])-pv: newc[stk]=newc.get(stk,0)+1
sname = h.drop_duplicates('stock').set_index('stock')['sname'].to_dict()
consensus = sorted(newc.items(), key=lambda x:-x[1])

# === crowding ===
crowd = pd.read_parquet(C/'crowding.parquet') if (C/'crowding.parquet').exists() else None

def won(x):
    x=float(x); return f"{x/1e8:,.0f}억" if abs(x)>=1e8 else f"{x/1e4:,.0f}만"

L=[f"📊 ETF 데일리 v2 [{BASE}]",""]
L.append("💧 괴리율 반전 기회 (국내·유동·NAV대비 -3%↓) ★검증 edge")
if len(opp):
    for t in opp.head(5).index:
        L.append(f"  • {nm(t)} 시장가 {opp.loc[t,'dev']*100:+.2f}% (NAV 대비)")
    L.append("  (과거 5일 평균 반등, 승률 76~81% · 기대치이지 보장 아님)")
else:
    L.append("  • 오늘 조건 충족 없음 (정상 — 평소 드뭄)")
L.append("")
L.append("🔥 이례적 거래폭증 ETF (20일평균 대비, 레버리지 제외)")
for t in top_surge.index:
    r = ret1.get(t, float('nan'))
    L.append(f"  • {nm(t)} 거래 {top_surge[t]:.1f}배 / {r*100:+.1f}%")
L.append("")
L.append("🏛 기관 순매수 (레버리지 제외)")
for t in inst.head(5).index: L.append(f"  • {nm(t)} +{won(inst[t])}")
L.append("")
L.append("🌏 외국인 순매수")
for t in foreign.head(5).index: L.append(f"  • {nm(t)} +{won(foreign[t])}")
L.append("")
L.append(f"🧭 (참고) 운용자 합의 신규편입 ({sp}→{sc}) — 약신호, 매수권유 아님")
shown=[x for x in consensus if x[1]>=2][:6]
if shown:
    for stk,n in shown: L.append(f"  • {sname.get(stk,stk)} : {n}개 운용자")
else:
    for stk,n in consensus[:5]: L.append(f"  • {sname.get(stk,stk)} : {n}개 운용자")
L.append("")
if crowd is not None:
    L.append("👥 액티브 운용자 합의 보유 Top5 (쏠림)")
    shown_c = 0
    for stk,r in crowd.iterrows():
        sn = sname.get(stk,str(stk))
        if any(k in sn for k in ['현금','원화','예금']): continue  # 현금성 제외
        L.append(f"  • {sn} : {int(r.n_holders)}개 ETF 보유")
        shown_c += 1
        if shown_c >= 5: break
    L.append("")
L.append("⚠️ 괴리율 함정 (시장가 vs NAV)")
for t in trap.index: L.append(f"  • {nm(t)} {trap[t]*100:+.2f}%")
L.append("")
L.append("※ 프로토타입 v2 · 정보용(투자권유 아님) · KRX")
msg="\n".join(L)
print(msg)

if SEND:
    import config, requests
    r=requests.post(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                    data={"chat_id":config.TELEGRAM_PRIVATE_ID,"text":msg},timeout=30)
    print(f"\n[발송] 개인봇 status={r.status_code} ok={r.json().get('ok')}")
