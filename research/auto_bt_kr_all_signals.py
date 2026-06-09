"""KR-only 시그널 표본 EDA — 외국인/기관 순매수가 production 픽의 승자/패자를 가르는가.
US 옵션A(거래대금 82배 분리)의 KR판. pykrx 표본(최근 ~15일 × Top10 픽) → 순매수 vs forward수익 분리력.
표본검증: full 7년 수집 전 신호 유무 먼저 확인. pykrx 1초 sleep 순차 (CLAUDE.md).
실행: python research/auto_bt_kr_all_signals.py
"""
import sys, json, time
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, r'C:\dev\claude-code\quant_py-main')
sys.stdout.reconfigure(encoding='utf-8')
import krx_auth
from pykrx import stock
ROOT = Path(r'C:\dev\claude-code\quant_py-main'); STATE = ROOT/'state'; DATA = ROOT/'data_cache'

print('pykrx 로그인...', flush=True)
print('login:', krx_auth.login(), flush=True)

ohlcv = pd.read_parquet(sorted(DATA.glob('all_ohlcv_2017*.parquet'))[-1]).replace(0,np.nan)

# 표본 날짜: forward 20d 측정 가능하도록 ohlcv 끝에서 25일+ 이전, ~5일 간격 15개
odates = [d.strftime('%Y%m%d') for d in ohlcv.index]
cand = [d for d in odates if '20260201' <= d <= '20260430']
sample_dates = cand[::max(1, len(cand)//15)][:15]
print(f'표본 {len(sample_dates)}일: {sample_dates[0]}~{sample_dates[-1]}', flush=True)

def fwd_ret(tk, d, n=20):
    ts = pd.Timestamp(d)
    if tk not in ohlcv.columns: return None
    s = ohlcv[tk]; idx = s.index.searchsorted(ts)
    if idx+n >= len(s): return None
    p0, p1 = s.iloc[idx], s.iloc[idx+n]
    return (p1/p0-1) if (pd.notna(p0) and pd.notna(p1) and p0>0) else None

def picks(d):
    fp = STATE/f'ranking_{d}.json'
    if not fp.exists(): return []
    data = json.load(open(fp, encoding='utf-8'))
    rows = sorted(data['rankings'], key=lambda r: r.get('weighted_rank', 999))
    return [str(r['ticker']).zfill(6) for r in rows[:10]]

def netbuy(d):
    """외국인/기관 순매수거래대금(억) by ticker — KOSPI+KOSDAQ 합침."""
    out = {'외국인': {}, '기관합계': {}}
    for inv in ['외국인', '기관합계']:
        for mkt in ['KOSPI', 'KOSDAQ']:
            try:
                time.sleep(1)
                df = stock.get_market_net_purchases_of_equities_by_ticker(d, d, mkt, inv)
                col = next((c for c in df.columns if '순매수거래대금' in str(c)), None)
                if col is not None:
                    for tk, v in (df[col]/1e8).to_dict().items():
                        out[inv][str(tk).zfill(6)] = v
            except Exception as e:
                print(f'  WARN {d} {mkt} {inv}: {str(e)[:60]}', flush=True)
    return out

rows = []
for d in sample_dates:
    pk = picks(d)
    if not pk: continue
    nb = netbuy(d)
    for tk in pk:
        fr = fwd_ret(tk, d)
        if fr is None: continue
        rows.append({'date': d, 'ticker': tk,
                     'foreign': nb['외국인'].get(tk, np.nan),
                     'inst': nb['기관합계'].get(tk, np.nan),
                     'fwd20': fr})
    print(f'  {d}: 픽 {len(pk)} 수집', flush=True)

df = pd.DataFrame(rows)
print(f'\n총 관측 {len(df)} (픽-일 단위)', flush=True)
if len(df) < 20:
    print('표본 부족 — EDA 신뢰 낮음', flush=True); sys.exit()

print('\n=== 외국인/기관 순매수 vs forward 20일 수익 분리력 ===', flush=True)
for sig in ['foreign', 'inst']:
    sub = df.dropna(subset=[sig, 'fwd20'])
    if len(sub) < 20: continue
    corr = sub[sig].corr(sub['fwd20'])
    # 승자(fwd>중앙값) vs 패자 순매수 평균
    med = sub['fwd20'].median()
    win = sub[sub['fwd20'] > med][sig].mean(); lose = sub[sub['fwd20'] <= med][sig].mean()
    # 순매수>0 픽 vs <0 픽 forward 수익
    pos = sub[sub[sig] > 0]['fwd20'].mean(); neg = sub[sub[sig] <= 0]['fwd20'].mean()
    print(f'\n[{sig}] n={len(sub)}', flush=True)
    print(f'  corr(순매수, fwd20) = {corr:+.3f}', flush=True)
    print(f'  승자 순매수평균 {win:+.1f}억 vs 패자 {lose:+.1f}억 (차이 {win-lose:+.1f}억)', flush=True)
    print(f'  순매수>0 픽 fwd {pos*100:+.1f}% vs 순매수≤0 픽 fwd {neg*100:+.1f}% (차이 {(pos-neg)*100:+.1f}%p)', flush=True)

print('\n해석: corr·승자패자차·순매수부호별 수익차가 뚜렷(예: >0이 +3%p↑)하면 full 수집 가치.', flush=True)
print('미미하면 KR-only 시그널도 거래대금처럼 효과 없음 → drop. (표본이라 결정 아닌 방향 제시)', flush=True)
df.to_csv(ROOT/'research'/'_kr_signals_sample.csv', index=False, encoding='utf-8-sig')
