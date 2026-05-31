"""ETF 스마트머니 데일리 브리핑 — 프로토타입 (회사/집 PC, krx_auth.login 필요).

콘텐츠: A 터진 ETF / B 외국인·기관 순매수 ETF / D 액티브 운용자 신규편입 / E 괴리율 함정경고.
프로토타입이라 universe/active 수를 작게 캡(빠른 표본). production은 N 늘리면 됨.
모든 pykrx 순차 + 1초. 결과는 개인봇으로만 발송(채널 X).
실행: python etf_research/daily_brief.py
"""
import sys, time, json
from pathlib import Path
import pandas as pd, numpy as np
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import krx_auth
if not krx_auth.login():
    print('[중단] KRX 로그인 실패'); sys.exit(1)
import pykrx.stock as s
import config, requests

SLEEP = 1.0
N_LIQ = 60      # 유동성 상위 universe (프로토타입)
N_INVESTOR = 40 # 투자자 순매수 스캔 (per-ticker)
N_ACTIVE = 8    # 액티브 PDF diff (per 2콜)
NAMES_CACHE = Path(__file__).parent / '_names_cache.json'
INST = ['금융투자','보험','투신','사모','은행','기타금융','연기금등','연기금']
# 스마트머니(B)·액티브(D)에서 제외: LP노이즈(레버리지/인버스) + 자금흐름 무의미(머니마켓/채권)
LEV_KW = ['레버리지','인버스','2X','2x','곱버스']
MM_KW = ['머니마켓','단기채','단기통안','채권','금리','CD금리','SOFR','국공채','종합채','크레딧','회사채','MMF','초단기']
def excl_lev(tk): return any(k in names.get(tk, '') for k in LEV_KW)
def excl_mm(tk): return any(k in names.get(tk, '') for k in MM_KW)


def bday(offset_days=0):
    d = (pd.Timestamp(BASE) - pd.Timedelta(days=offset_days)).strftime('%Y%m%d')
    return s.get_nearest_business_day_in_a_week(d)


BASE = s.get_nearest_business_day_in_a_week()
PREV1 = bday(1); time.sleep(SLEEP)
PREV5 = bday(7); time.sleep(SLEEP)   # PDF diff 비교용 (~5거래일 전)
print(f'기준일 {BASE} (전일 {PREV1}, diff기준 {PREV5})', flush=True)

names = json.loads(NAMES_CACHE.read_text(encoding='utf-8')) if NAMES_CACHE.exists() else {}
def nm(tk):
    if tk not in names:
        try:
            v = s.get_etf_ticker_name(tk)
            if hasattr(v, 'iloc'): v = v.iloc[0]   # 일부 티커 Series 반환 방어
            names[tk] = str(v)
        except: names[tk] = tk
        time.sleep(SLEEP)
    return names[tk]

# === 유니버스 + A (터진 ETF) : price_change 1콜 ===
chg = s.get_etf_price_change_by_ticker(PREV1, BASE); time.sleep(SLEEP)
chg.index = chg.index.astype(str)
valcol = next(c for c in chg.columns if '거래대금' in c)
retcol = next(c for c in chg.columns if '등락' in c)
liquid = chg.sort_values(valcol, ascending=False).head(N_LIQ).index.tolist()
top_val = chg.loc[liquid].sort_values(valcol, ascending=False).head(5)
top_ret = chg.loc[liquid].sort_values(retcol, ascending=False).head(5)

# === E (괴리율) : ohlcv_by_ticker 1콜로 전종목 NAV·종가 ===
bt = s.get_etf_ohlcv_by_ticker(BASE); time.sleep(SLEEP)
bt.index = bt.index.astype(str)
dev = {}
for tk in liquid:
    if tk in bt.index and bt.loc[tk,'NAV'] > 0:
        dev[tk] = bt.loc[tk,'종가']/bt.loc[tk,'NAV'] - 1
dev = pd.Series(dev).sort_values()
trap = pd.concat([dev.head(3), dev.tail(3)])  # 음/양 극단 괴리

# === B (스마트머니) : 유동 상위, 레버리지/인버스 제외, 투자자별 순매수 ===
print('투자자별 순매수 스캔...', flush=True)
for tk in liquid: nm(tk)  # 이름 로드(제외필터용, 캐시됨)
sm_universe = [tk for tk in liquid if not excl_lev(tk)][:N_INVESTOR]
foreign, inst = {}, {}
for i, tk in enumerate(sm_universe):
    try:
        tv = s.get_etf_trading_volume_and_value(BASE, BASE, tk)
        nb = tv[('거래대금','순매수')] if isinstance(tv.columns, pd.MultiIndex) else tv['순매수']
        f = sum(nb.get(k,0) for k in ['외국인','기타외국인'])
        ins = sum(nb.get(k,0) for k in INST)
        foreign[tk] = f; inst[tk] = ins
    except Exception as e:
        pass
    time.sleep(SLEEP)
foreign = pd.Series(foreign).sort_values(ascending=False)
inst = pd.Series(inst).sort_values(ascending=False)

# === D (액티브 운용자 신규편입) : 주식형 액티브만(머니마켓/채권 제외) PDF diff ===
print('액티브 PDF diff...', flush=True)
active_liq = [tk for tk in liquid if '액티브' in nm(tk) and not excl_mm(tk) and not excl_lev(tk)][:N_ACTIVE]
active_moves = []
for tk in active_liq:
    try:
        p0 = s.get_etf_portfolio_deposit_file(tk, BASE); time.sleep(SLEEP)
        pp = s.get_etf_portfolio_deposit_file(tk, PREV5); time.sleep(SLEEP)
        p0.index = p0.index.astype(str); pp.index = pp.index.astype(str)
        ncol = next((c for c in p0.columns if '종목명' in c), None)
        p0u = p0[~p0.index.duplicated()]  # 중복 인덱스 제거(머니마켓 CP 등 방어)
        new = [t for t in p0u.index if t not in set(pp.index)]
        new_names = []
        for t in new:
            v = p0u.loc[t, ncol] if ncol else t
            v = str(v).strip()
            if v and not v.startswith(('F0','현금','원화','KRW')):  # CP/현금성 제외
                new_names.append(v)
        new_names = list(dict.fromkeys(new_names))[:3]  # 중복제거 상위3
        if new_names:
            active_moves.append(f"  • {nm(tk)}: 신규 {', '.join(new_names)}")
    except Exception:
        pass

def won(x):
    x = float(x)
    if abs(x) >= 1e8: return f"{x/1e8:,.0f}억"
    return f"{x/1e4:,.0f}만"

# === 메시지 조립 ===
L = []
L.append(f"📊 ETF 스마트머니 데일리 [{BASE}] (프로토타입)")
L.append("")
L.append("🔥 오늘 터진 ETF (거래대금)")
for tk in top_val.index:
    L.append(f"  • {nm(tk)} {top_val.loc[tk,retcol]:+.1f}% / 대금 {won(top_val.loc[tk,valcol])}")
L.append("")
L.append("📈 상승률 상위")
for tk in top_ret.index:
    L.append(f"  • {nm(tk)} {top_ret.loc[tk,retcol]:+.1f}%")
L.append("")
L.append(f"🌏 외국인 순매수 ETF (유동 상위 {N_INVESTOR} 중)")
for tk in foreign.head(5).index:
    L.append(f"  • {nm(tk)} +{won(foreign[tk])}")
L.append("")
L.append("🏛 기관 순매수 ETF")
for tk in inst.head(5).index:
    L.append(f"  • {nm(tk)} +{won(inst[tk])}")
L.append("")
L.append("🧭 액티브 운용자 신규편입 (최근 ~5거래일)")
L += active_moves if active_moves else ["  • (표본 액티브에서 변동 없음)"]
L.append("")
L.append("⚠️ 괴리율 함정 경고 (시장가 vs NAV)")
for tk in trap.index:
    L.append(f"  • {nm(tk)} {trap[tk]*100:+.2f}%")
L.append("")
L.append("※ 프로토타입 · 정보용(투자권유 아님) · 데이터 KRX")
msg = "\n".join(L)
print("\n" + msg, flush=True)

# === 개인봇 발송 (채널 X) ===
r = requests.post(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                  data={"chat_id": config.TELEGRAM_PRIVATE_ID, "text": msg}, timeout=30)
print(f"\n[발송] 개인봇 {config.TELEGRAM_PRIVATE_ID} status={r.status_code} ok={r.json().get('ok')}", flush=True)
NAMES_CACHE.write_text(json.dumps({k: str(v) for k, v in names.items()}, ensure_ascii=False), encoding='utf-8')
