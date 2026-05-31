"""괴리율 반전 기회 알림 — 검증된 edge의 제품화 (오프라인, _cache).
필터(dev_reversion 검증 기반): 국내기초 + 거래대금≥20억 + 음괴리 ≤ -4% (또는 -3%).
해외기초/합성/레버리지/인버스 제외(시차 구조적 괴리 = 반등 약, 함정).
오늘 NAV 대비 할인 거래 + 유동 충분 = 5일 평균 반등 기대(과거 승률 76~81%, 단 보장 아님).
실행: python etf_research/dev_alert.py [--send] [--thr -0.04]
"""
import sys, json
from pathlib import Path
import pandas as pd, numpy as np
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
C = Path(__file__).parent / '_cache'
SEND = '--send' in sys.argv
THR = -0.04
if '--thr' in sys.argv: THR = float(sys.argv[sys.argv.index('--thr')+1])

names = json.loads((C/'names.json').read_text(encoding='utf-8'))
# 해외기초/합성/레버리지/인버스/원자재 = 시차·구조적 괴리 → 제외
EXCL = ['레버리지','인버스','2X','2x','곱버스','합성','(H)','미국','차이나','중국','인도','베트남','일본','유럽','글로벌',
        '월드','선진국','신흥','원유','WTI','금','은','구리','달러','엔','해외','나스닥','S&P','필라델피아','항셍','니케이']
def domestic(t): return not any(k in names.get(t,'') for k in EXCL)

oh = pd.read_parquet(C/'ohlcv_liquid.parquet'); oh['etf']=oh['etf'].astype(str)
BASE = oh['date'].max()
b = oh[oh.date==BASE].copy()
b['dev'] = (b['close']/b['nav'] - 1).where(b['nav']>0)
# 필터: 국내 + 거래대금 20억+ + 음괴리 ≤ THR
cand = b[(b['value']>=2e9) & (b['dev']<=THR) & (b['etf'].map(domestic))].sort_values('dev')

L = [f"💧 괴리율 반전 기회 [{BASE}] (음괴리 ≤ {THR*100:.0f}%, 국내·유동)"]
L.append(f"검증: 과거 이 조건 → 5일 평균 반등(승률 76~81%). ※기대치이지 보장 아님")
L.append("")
if len(cand):
    for r in cand.head(10).itertuples():
        L.append(f"  • {names.get(r.etf,r.etf)}  시장가 {r.dev*100:+.2f}% (NAV 대비) / 대금 {r.value/1e8:.0f}억")
else:
    L.append(f"  • 오늘 조건 충족 ETF 없음 (정상 — 평소 드뭄, 연 20~88회)")
L.append("")
L.append("※ 해외기초/레버리지/인버스 제외(시차 구조적 괴리=함정). 정보용·투자권유 아님.")
msg = "\n".join(L)
print(msg)
if SEND:
    import config, requests
    r = requests.post(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                      data={"chat_id": config.TELEGRAM_PRIVATE_ID, "text": msg}, timeout=30)
    print(f"\n[발송] 개인봇 status={r.status_code} ok={r.json().get('ok')}")
