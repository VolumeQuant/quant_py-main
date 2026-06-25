# -*- coding: utf-8 -*-
"""★융합(확신가중) forward 추적기 + 프로덕션 상태 생성 — 독립 NTM 수집 / cross-sec 상위100 (2026-06-25).

방식 (백테스트로 결정, look-ahead 상한 Calmar 5.52 = 최고):
  - 확인 = 그날 '컨센 보유 유니버스(끈적, 1회 스캔)' 의 기대성장(선행EPS/TTM실적EPS) **cross-sec 상위100**.
    (절대컷 1.3x=5.05·연속=4.97 보다 우월. rank기반이라 컨센 낙관편향에도 robust)
  - production 보유(rank<=3) 중 그 상위100에 들면 ✅ → 확신가중 ×3, 아니면 ×1, 정규화.
설계 원칙:
  - kr eps(ntm_screening) 의존 0. FnGuide 직접 수집(순차, 병렬 금지). 커버셋 1회 스캔 후 그것만 매일.
  - TTM 분모: 지배주주당기순이익 → 없으면 당기순이익 폴백(브이엠처럼 지배지분 구분없는 회사).
출력: fusion_state.json(메시지용·held+weights) / conviction_fusion_log.csv(OOS 누적) / fusion_consensus_cache.csv(PIT)
★검증/실배포 판단은 look-ahead BT(상한)가 아니라 이 forward 누적 60일+로. 메시지는 '제안 표시'만.
실행: python kr_eps_momentum/conviction_fusion_tracker.py
"""
import sys, io, os, glob, json, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
import fnguide_crawler as fc
LOG = os.path.join(HERE, 'conviction_fusion_log.csv')
CACHE = os.path.join(HERE, 'fusion_consensus_cache.csv')
COVERED = os.path.join(HERE, 'fusion_covered_universe.json')
STATE = os.path.join(HERE, 'fusion_state.json')
TOPN_CONFIRM = 100   # cross-sec 상위N = 확인셋
CW = 3.0             # (구) binary 확신가중 배수
# 2026-06-25 강도 차등: 확인종목 비중 = 1 + K_STR×(기대성장-1), CAP 상한. grow 강할수록 더 비중.
# ★2026-06-26 CAP 5→3 (선행PER<20 자격으로 재스윕): 구 cap5는 cross-sec 자격 기준 스윕이라 stale.
#   선행PER<20 설계서 재스윕(_conviction_cap_validate.py): cap3 Calmar 4.92>cap5 4.56 + MDD -26<-29%.
#   WF 전구간(약세 동일·24-26 우위, 19-21만 소폭양보) + LOWO 6종목 전부 cap3≥cap5 = robust.
#   ⚠️ look-ahead 상한 기준 — 표시제안만(사이징 본인판단). 실검증은 forward 누적.
CONV_K = float(os.environ.get('FUSION_CONV_K', '2.0'))    # grow 비례 기울기
CONV_CAP = float(os.environ.get('FUSION_CONV_CAP', '3.0'))  # 최대 배수 (2026-06-26 5→3 재스윕)
FETCH_DELAY = 1.2

# 2026-06-25 ★확인 자격 = forward PER < FWD_PER_GATE (구 'cross-sec 상위100' 폐기).
# 사용자 알파: trailing PER 높아도 forward PER<20이면 이익폭증=강매수. forward PER 단독 IC 0.147 >> 기대성장 0.041.
# 자격을 기대성장 비율 상위N(약신호)로 정하던 게 오류 → forward PER<20(강신호)로 자격, 기대성장은 비중 크기.
# 기간별 BT(강세19-21·최근24-26): min Calmar 정점 fwPER<20(plateau 15~35), 게이트없음보다 우위 = robust.
# ⚠️look-ahead proxy(미래실적) 상한 — 상대비교는 확실, 절대성과는 컨센누적 후. 표시제안만(매매 불변).
FWD_PER_GATE = float(os.environ.get('FUSION_FWD_PER_GATE', '20.0'))

px = pd.read_parquet(sorted(glob.glob(ROOT + '/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0, np.nan)
pcol = {c: i for i, c in enumerate(px.columns)}; parr = px.values
pdi = {d.strftime('%Y%m%d'): i for i, d in enumerate(px.index)}; ptd = list(pdi.keys())
mc = pd.read_parquet(sorted(glob.glob(ROOT + '/data_cache/market_cap_ALL_*.parquet'))[-1])

_NM = None
def name(t6):
    global _NM
    if _NM is None:
        try: _NM = json.load(open(os.path.join(HERE, 'ticker_info_cache.json'), encoding='utf-8'))
        except Exception: _NM = {}
    for k in (t6, t6 + '.KS', t6 + '.KQ'):
        if k in _NM: return _NM[k].get('shortName', t6)
    return t6

def ttm_eps(t6):
    p = ROOT + f'/data_cache/fs_dart_{t6}.parquet'
    if not os.path.exists(p) or t6 not in mc.index: return None
    fs = pd.read_parquet(p); fs['rcept_dt'] = pd.to_datetime(fs['rcept_dt'], errors='coerce')
    sh = mc.loc[t6, '상장주식수']
    if not (sh > 0): return None
    for acct in ('지배주주당기순이익', '당기순이익'):
        q = fs[(fs['공시구분'] == 'q') & (fs['계정'] == acct) & (fs['rcept_dt'].notna())].sort_values('rcept_dt')
        v = q['값'].astype(float).values
        if len(v) >= 4:
            return (v[-4:].sum() * 1e8) / sh
    return None

def load_covered():
    if os.path.exists(COVERED):
        return json.load(open(COVERED, encoding='utf-8')).get('covered', [])
    return []

def latest_production():
    f = sorted(glob.glob(ROOT + '/state/ranking_*.json'))[-1]
    bd = os.path.basename(f)[8:16]
    rk = sorted(json.load(open(f, encoding='utf-8'))['rankings'], key=lambda z: z.get('rank', 99))
    return bd, [x['ticker'] for x in rk[:3]]

def load_cache():
    if os.path.exists(CACHE):
        return pd.read_csv(CACHE, dtype={'ticker': str, 'date': str})
    return pd.DataFrame(columns=['date', 'ticker', 'forward_eps', 'eps_cy', 'eps_ny', 'analyst_count', 'has_consensus'])

def collect_consensus(tickers, day8):
    """커버셋에 FnGuide 컨센 순차 수집(당일 캐시 재사용). eps_cy(당해)/eps_ny(차기)도 저장 → NTM 합성용.
    재수집 조건: 당일치 없거나 eps_ny 결측(구버전 캐시)."""
    cache = load_cache()
    cur0 = cache[cache['date'] == day8]
    have = set(cur0[cur0['eps_ny'].notna()]['ticker']) if 'eps_ny' in cur0.columns else set()
    todo = [t for t in tickers if t not in have]
    if todo:
        # 구버전 당일 행(eps_ny 없음) 제거 후 재수집
        cache = cache[~((cache['date'] == day8) & (cache['ticker'].isin(todo)))]
        print(f"  FnGuide 컨센 수집 {len(todo)}종목 (순차, ~{len(todo)*FETCH_DELAY/60:.0f}분)...", flush=True)
        new = []
        for i, t in enumerate(todo, 1):
            try:
                d = fc.get_consensus_data(t)
                new.append({'date': day8, 'ticker': t, 'forward_eps': d.get('forward_eps') if d else None,
                            'eps_cy': d.get('eps_cy') if d else None, 'eps_ny': d.get('eps_ny') if d else None,
                            'analyst_count': d.get('analyst_count') if d else None,
                            'has_consensus': int(bool(d and d.get('has_consensus')))})
            except Exception:
                new.append({'date': day8, 'ticker': t, 'forward_eps': None, 'eps_cy': None, 'eps_ny': None, 'analyst_count': None, 'has_consensus': 0})
            if i % 50 == 0: print(f"    {i}/{len(todo)}", flush=True)
            time.sleep(FETCH_DELAY)
        cache = pd.concat([cache, pd.DataFrame(new)], ignore_index=True)
        cache.to_csv(CACHE, index=False)
    cur = cache[cache['date'] == day8]
    # NTM(선행12개월) 합성: 당해×(12-월)/12 + 차기×월/12. 차기 없으면 forward_eps(당해) 폴백.
    mth = int(day8[4:6])
    out = {}
    for _, r in cur.iterrows():
        cy = r.get('eps_cy'); ny = r.get('eps_ny'); fe = r.get('forward_eps')
        if pd.notna(cy) and pd.notna(ny) and cy and ny:
            out[r['ticker']] = cy * (12 - mth) / 12 + ny * mth / 12   # NTM 합성
        elif pd.notna(fe) and fe > 0:
            out[r['ticker']] = fe   # 차기 결측 → 당해 폴백
    return {t: v for t, v in out.items() if v and v > 0}

def price_on(t6, d8):
    if t6 not in pcol or d8 not in pdi: return None
    v = parr[pdi[d8], pcol[t6]]; return float(v) if v > 0 else None

def latest_prices(day8):
    """★최신 거래일 전종목 종가 (pykrx 1호출). forward PER은 가격 변동에 민감 → OHLCV(증분지연) 대신 실시간.
    실패 시 빈 dict(price_on OHLCV 폴백). pykrx 1호출이라 부담 적음(순차원칙 무관)."""
    try:
        from pykrx import stock
        try:
            import krx_auth; krx_auth.login()
        except Exception:
            pass
        df = stock.get_market_ohlcv_by_ticker(day8, market="ALL")
        return {t: float(df.loc[t, '종가']) for t in df.index if df.loc[t, '종가'] > 0}
    except Exception as e:
        print(f"  ⚠️ pykrx 최신가 실패({type(e).__name__}), OHLCV 폴백 — fwd_per 가격 지연 가능", flush=True)
        return {}

def main():
    pbd, held3 = latest_production()
    covered = load_covered()
    if not covered:
        print("⚠️ fusion_covered_universe.json 없음 — fusion_universe_scan.py 먼저 실행 필요. 중단.")
        return
    # 보유종목은 커버셋에 없어도 컨센 확인하려 추가 수집
    targets = sorted(set(covered) | set(held3))
    fwd_eps = collect_consensus(targets, pbd)
    # 기대성장 = 선행EPS / TTM실적EPS, forward PER = 최신종가 / 선행EPS (커버 유니버스 전체)
    # ★fwd_per 가격은 pykrx 최신종가 우선(가격 변동 민감, OHLCV 증분지연 시 자격 오판) → 폴백 OHLCV.
    latest_px = latest_prices(pbd)
    def cur_price(t6):
        return latest_px.get(t6) or price_on(t6, pbd) or price_on(t6, ptd[-1])
    grow = {}; fwdper = {}
    for t in targets:
        fe = fwd_eps.get(t); te = ttm_eps(t); p0 = cur_price(t)
        if fe and te and te > 0: grow[t] = fe / te
        if fe and fe > 0 and p0: fwdper[t] = p0 / fe
    # ★확인 자격 = forward PER < FWD_PER_GATE (구 'cross-sec 상위100' 폐기, 2026-06-25).
    #   근거: forward PER 단독 IC 0.147 >> 기대성장 비율 0.041. 자격=forward PER<20 게이트, 비중=기대성장 비례.
    #   기간별 BT(강세19-21·최근24-26 쪼갬) min Calmar 정점 fwPER<20(plateau 15~35), 게이트없음보다 우위.
    confirm = set(t for t in grow if t in fwdper and fwdper[t] < FWD_PER_GATE)
    print(f"\n=== 융합 forward 추적기 (forward PER<{FWD_PER_GATE:.0f} 자격 + 기대성장 비례 k{CONV_K:.0f}cap{CONV_CAP:.0f}) ===")
    print(f"production {pbd} / 커버 {len(covered)} / 기대성장계산 {len(grow)} / forwardPER<{FWD_PER_GATE:.0f} 자격 {len(confirm)}종목\n")
    # 보유 top3 확인 + 가중치
    held_info, raw_w = [], []
    for i, t in enumerate(held3, 1):
        g = grow.get(t); isc = t in confirm; fper = fwdper.get(t)
        # 자격(forward PER<게이트)이면 기대성장 비례 비중, 아니면 1.
        if isc:
            w = min(1.0 + CONV_K * max((g or 1.0) - 1.0, 0.0), CONV_CAP)
        else:
            w = 1.0
        raw_w.append(w)
        held_info.append({'ticker': t, 'name': name(t), 'rank': i, 'confirmed': int(isc),
                          'grow': round(g, 4) if g else None, 'fwd_per': round(fper, 1) if fper else None,
                          'has_consensus': int(fwd_eps.get(t) is not None)})
    tot = sum(raw_w); wpct = [round(w / tot * 100, 1) for w in raw_w]
    for hi, wp in zip(held_info, wpct):
        g = hi['grow']; fp = hi['fwd_per']
        gs = f"+{(g-1)*100:.0f}% ({g:.2f}x)" if g else ('NA(컨센없음)' if not hi['has_consensus'] else 'NA(TTM없음)')
        fps = f"fwdPER {fp}" if fp else "fwdPER NA"
        print(f"{hi['rank']}. {hi['name'][:12]:12s} {'✅확인' if hi['confirmed'] else '  미확인':7s} {gs:18s} {fps:12s} → 비중 {wp}%")
    # 상태파일(메시지용)
    json.dump({'prod_date': pbd, 'method': f'forward PER<{FWD_PER_GATE:.0f} 자격 + 기대성장 비례(k{CONV_K:.0f}cap{CONV_CAP:.0f})', 'cw': CONV_CAP,
               'fwd_per_gate': FWD_PER_GATE, 'held': held_info, 'weights_pct': wpct, 'n_covered': len(covered), 'n_grow': len(grow)},
              open(STATE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    # 로그 누적(OOS)
    newrows = [{'run_date': pbd, 'prod_date': pbd, 'ticker': h['ticker'], 'name': h['name'], 'rank': h['rank'],
                'has_consensus': h['has_consensus'], 'grow': h['grow'] if h['grow'] else '',
                'confirmed': h['confirmed'], 'weight_pct': wp, 'entry_px': cur_price(h['ticker'])}
               for h, wp in zip(held_info, wpct)]
    log = pd.read_csv(LOG, dtype={'ticker': str, 'run_date': str, 'prod_date': str}) if os.path.exists(LOG) else pd.DataFrame()
    log = pd.concat([log, pd.DataFrame(newrows)], ignore_index=True).drop_duplicates(['run_date', 'ticker'], keep='last')
    log.to_csv(LOG, index=False)
    print(f"\n상태 → fusion_state.json / 로그 {log['run_date'].nunique()}일치")
    # 누적 OOS
    last8 = ptd[-1]; cf, un = [], []
    for _, r in log.iterrows():
        d0 = str(r['prod_date']); p0 = price_on(str(r['ticker']).zfill(6), d0); p1 = price_on(str(r['ticker']).zfill(6), last8)
        if p0 and p1 and d0 < last8: (cf if r['confirmed'] == 1 else un).append((p1 / p0 - 1) * 100)
    if cf or un:
        print(f"=== 누적 OOS (→{last8}) 확인 {np.mean(cf) if cf else 0:+.2f}%(n={len(cf)}) vs 미확인 {np.mean(un) if un else 0:+.2f}%(n={len(un)})")
    nd = log['run_date'].nunique()
    print(f"  ⚠️ {nd}일 누적 = {'예비(증거아님)' if nd < 60 else '검증시작'}. 60일+ 권장.")

if __name__ == '__main__':
    main()
