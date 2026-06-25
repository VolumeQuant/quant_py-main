# -*- coding: utf-8 -*-
"""📊 기대성장 Sleeve (Forward Growth) — KR판 (US 미러, 2026-06-25 신규).
기대성장 = NTM 예상EPS / TTM 실적EPS. 상위 15 동일가중, 월 1회 리밸런스, 약세장(KOSPI MA20/80) 현금.
메인 멀티팩터 시스템과 별개 sleeve. 개인봇 페이퍼 검증(채널 X).
실행: python kr_eps_momentum/forward_growth_sleeve.py        (드라이런=메시지만 출력)
      python kr_eps_momentum/forward_growth_sleeve.py --send  (개인봇 전송)
state: forward_sleeve_state.json (포트폴리오·진입가·인셉션·peak)"""
import sqlite3, sys, io, os, glob, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(HERE, 'eps_momentum_data_kr.db')
STATE = os.path.join(HERE, 'forward_sleeve_state.json')
N_HOLD = 15
TODAY = None  # 자동(최신 NTM일)

def load_prices():
    px = pd.read_parquet(sorted(glob.glob(ROOT + '/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0, np.nan)
    mc = pd.read_parquet(sorted(glob.glob(ROOT + '/data_cache/market_cap_ALL_*.parquet'))[-1])
    return px, mc

def regime(px):
    """KOSPI MA20>MA80, 5일 확인 → boost/defense (메인 시스템과 동일)"""
    kc = pd.read_parquet(ROOT + '/data_cache/kospi_yf.parquet').iloc[:, 0]
    ma20, ma80 = kc.rolling(20).mean(), kc.rolling(80).mean()
    md, stk, ss = True, 0, None
    for d in kc.index:
        if pd.isna(ma80.get(d, np.nan)): continue
        s = bool(ma20[d] > ma80[d]); stk = stk + 1 if s == ss else 1; ss = s
        if stk >= 5 and md != s: md = s
    return 'boost' if md else 'defense'

def ttm_eps(tk6, mc):
    p = ROOT + f'/data_cache/fs_dart_{tk6}.parquet'
    if not os.path.exists(p) or tk6 not in mc.index: return None
    fs = pd.read_parquet(p); fs['rcept_dt'] = pd.to_datetime(fs['rcept_dt'], errors='coerce')
    q = fs[(fs['공시구분'] == 'q') & (fs['계정'] == '지배주주당기순이익') & (fs['rcept_dt'].notna())].sort_values('rcept_dt')
    v = q['값'].astype(float).values
    if len(v) < 4: return None
    sh = mc.loc[tk6, '상장주식수']
    return (v[-4:].sum() * 1e8) / sh if sh > 0 else None

_NAME_CACHE = None
def name_of(tk6):
    global _NAME_CACHE
    if _NAME_CACHE is None:
        try: _NAME_CACHE = json.load(open(os.path.join(HERE, 'ticker_info_cache.json'), encoding='utf-8'))
        except Exception: _NAME_CACHE = {}
    for k in (tk6, tk6 + '.KS', tk6 + '.KQ'):
        if k in _NAME_CACHE: return _NAME_CACHE[k].get('shortName', tk6)
    return tk6

def compute_picks(mc):
    c = sqlite3.connect(DB)
    last = c.execute('SELECT MAX(date) FROM ntm_screening').fetchone()[0]
    df = pd.read_sql(f"SELECT ticker,ntm_current,is_turnaround FROM ntm_screening WHERE date='{last}'", c)
    df['tk6'] = df['ticker'].str[:6]
    rows = []
    for _, r in df.iterrows():
        if not r['ntm_current'] or r['ntm_current'] <= 0: continue
        te = ttm_eps(r['tk6'], mc)
        if te is None or te <= 0: continue   # 흑전(적자) 제외 — 기대성장 ratio 불가
        rows.append((r['tk6'], r['ntm_current'] / te))
    g = pd.DataFrame(rows, columns=['tk6', 'gap']).sort_values('gap', ascending=False)
    g = g[g['gap'] < 15]   # 19x+ 초저점 노이즈 제외(매출 EPS 거의 0)
    return last, g.head(N_HOLD)['tk6'].tolist(), dict(zip(g['tk6'], g['gap']))

def cur_price(tk6, mc):
    return float(mc.loc[tk6, '종가']) if tk6 in mc.index else None

def main(send=False):
    px, mc = load_prices()
    reg = regime(px)
    last, picks, gapmap = compute_picks(mc)
    st = json.load(open(STATE, encoding='utf-8')) if os.path.exists(STATE) else None
    month = last[:7]

    # === 약세장 → 현금 ===
    if reg == 'defense':
        msg = (f"📊 <b>기대성장 Sleeve (Forward Growth)</b>\n기준일 {last}\n\n"
               f"🛡️ <b>방어 국면 — sleeve 현금</b>\n약세장(KOSPI 20/80선 이탈)이라 고성장주 변동 회피, 현금 보유.\n\n"
               f"※ 메인 멀티팩터 시스템과 별개 sleeve · 페이퍼 검증")
        st = {**(st or {}), 'mode': 'cash', 'last_run': last}
        json.dump(st, open(STATE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        return out(msg, send)

    # === 리밸런스 판정 (첫run 또는 월 변경 또는 직전 현금) ===
    need_rebal = (st is None) or (st.get('mode') == 'cash') or (st.get('rebal_month') != month)
    if need_rebal:
        port = [{'tk6': t, 'entry': cur_price(t, mc), 'name': name_of(t), 'gap': gapmap.get(t)} for t in picks]
        port = [p for p in port if p['entry']]
        incept = (st or {}).get('inception', last)
        st = {'mode': 'hold', 'inception': incept, 'rebal_month': month, 'rebal_date': last,
              'portfolio': port, 'last_run': last, 'peak': (st or {}).get('peak', 1.0)}
        lines = [f"📊 <b>기대성장 Sleeve (Forward Growth)</b>", f"기준일 {last} · 시장 기대 EPS성장 상위 {len(port)} 분산", "",
                 f"📈 운용 {incept}~", "", "━━━━━━━━━━━━━━━", "🔄 <b>월간 리밸런스 (신규 구성)</b>", "━━━━━━━━━━━━━━━"]
        for i, p in enumerate(port, 1):
            lines.append(f"{i}. {p['name'][:12]} · 기대성장 {(p['gap']-1)*100:+.0f}% (gap {p['gap']:.1f}x)")
    else:
        # === 보유 중 — 성과 갱신 ===
        port = st['portfolio']
        rets = [(cur_price(p['tk6'], mc) / p['entry'] - 1) for p in port if p['entry'] and cur_price(p['tk6'], mc)]
        cum = float(np.mean(rets)) if rets else 0.0  # 동일가중
        peak = max(st.get('peak', 1.0), 1 + cum); mdd = (1 + cum) / peak - 1
        st['peak'] = peak; st['last_run'] = last
        lines = [f"📊 <b>기대성장 Sleeve (Forward Growth)</b>", f"기준일 {last} · 보유 {len(port)}종목", "",
                 f"🟢 <b>보유 중</b>  누적 {cum*100:+.1f}% (운용 {st['inception']}~)", f"     MDD {mdd*100:.1f}%", "",
                 "━━━━━━━━━━━━━━━", "보유 종목 (기대성장순)", "━━━━━━━━━━━━━━━"]
        for i, p in enumerate(port, 1):
            cp = cur_price(p['tk6'], mc); r = (cp/p['entry']-1)*100 if (cp and p['entry']) else 0
            lines.append(f"{i}. {p['name'][:12]} {r:+.1f}%")
    lines += ["", "━━━━━━━━━━━━━━━", "📌 <b>운영 규칙</b>",
              "기대성장 = 향후12개월 예상EPS ÷ 최근12개월 실적EPS",
              f"상위 {N_HOLD} 동일가중 · 월 1회 리밸런스 · 약세장(KOSPI 20/80) 현금",
              "※ 메인 멀티팩터 시스템과 별개 sleeve · 페이퍼 검증(채널 X)"]
    json.dump(st, open(STATE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return out("\n".join(lines), send)

def out(msg, send):
    print(msg)
    if send:
        import requests
        sys.path.insert(0, ROOT)
        try:
            import config
            pid = getattr(config, 'TELEGRAM_PRIVATE_ID', None) or config.TELEGRAM_CHAT_ID
            r = requests.post(f'https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage',
                              {'chat_id': pid, 'text': msg, 'parse_mode': 'HTML'}, timeout=30)
            print(f"\n[개인봇 전송 {r.status_code}]")
        except Exception as e:
            print(f"\n[전송 실패: {e}]")

if __name__ == '__main__':
    main(send='--send' in sys.argv)
