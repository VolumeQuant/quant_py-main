# -*- coding: utf-8 -*-
"""방어신호 연구 마무리 (2026-06-19): "삼성/하이닉스 착시" → ex-메가/동일가중 국면 검증.
사용자 직감: 코스피는 삼성·하이닉스가 떠받쳐 boost지만 시장 광범위 약세.
검증한 국면 기준 후보:
 ① 코스피 ex-삼성하이닉스 (시총가중)  → 기각: 2.86, 여전히 차상위 메가에 가려짐, 현재신호 boost
 ② 중앙값 수익지수 (이상치 강건)       → 기각: -0.03, 무의미(중앙값 일수익 ~0)
 ③ 상위N(50~300) 동일가중 = KOSPI200프록시 → 기각: 1.98~2.76, MDD 36~46%, 현재신호 boost
                                            (=대형주는 멀쩡, 약세는 소형주에 있음)
 ④ 전종목 동일가중                      → ★경쟁력 있음(아래 공정비교)

★공정비교 (코스피도 같은 6개 MA설정으로 CV 측정 — 한쪽만 CV 들이대면 불공정):
  현행 코스피     : 6설정평균 3.345  CV 0.159  최소 2.599 | WF 19-21 2.15 / 약세 0.61 / 24-26 14.36
  전종목 동일가중 : 6설정평균 3.647  CV 0.199  최소 2.575 | WF 19-21 3.31 / 약세 0.67 / 24-26 14.07
  → 동일가중이 평균 더 높고(3.65>3.35), 최악설정 동급(2.58≈2.60), WF 2/3블록(약세포함) 우위.
    헤드라인 MA20/80 = 4.58 vs 4.08, MDD 24% vs 25.9%. CV만 약간 높음(0.199 vs 0.159).

결론(2026-06-19):
 - 내 초기 "불안정해서 기각"은 불공정했음(코스피 CV와 비교 안 함). 동일가중은 실제로 경쟁력~소폭우위.
 - 단 차이가 노이즈 밴드(±0.10~0.5) 안 + CV 소폭 열위 + 국면기준 교체는 최고 레버리지/최고위험 변경
   (corpaction 사고 교훈: marginal 개선으로 배포 금지) → 프로덕션 국면 교체는 보류.
 - 동일가중 = #1 미래 후보 + 현재 "DEFENSE" 점등 = 광범위 약세 실재(사용자 직감 맞음).
   방어 레버 = 시스템 룰 변경 아님 → 메타 현금버퍼(사용자 영역).
 - "약세"의 정체: 대형주(상위N 동일가중=boost)는 버팀, 소형주(전종목 동일가중=defense)가 무너짐.
   시스템은 시총≥1000억 대형/중형 + MA120필터로 약한 소형주를 안 보유 → 직접 노출 적음.
"""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices = pd.read_parquet(sorted(glob.glob(P + '/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0, np.nan)
kc = pd.read_parquet(P + '/data_cache/kospi_yf.parquet').iloc[:, 0]
biz = prices[prices.notna().sum(axis=1) >= 100]
ew = (1 + biz.pct_change(fill_method=None).mean(axis=1)).cumprod()
G3 = ('rev_z', 'oca_z', 'gp_growth_z', 0.4, 0.4, 0.2)
ar, days = {}, []
for f in sorted(glob.glob(P + '/state/ranking_*.json')):
    d = os.path.basename(f)[8:16]
    if d.isdigit() and len(d) == 8 and d >= '20190102':
        ar[d] = json.load(open(f, encoding='utf-8'))['rankings']; days.append(d)
days = sorted(days)


def reg_idx(idx, sh_, lo_, cf, days):
    s_ = idx.rolling(sh_).mean(); l_ = idx.rolling(lo_).mean()
    reg = {}; md = True; stk = 0; ss = None
    for d in days:
        ts = pd.Timestamp(d[:4] + '-' + d[4:6] + '-' + d[6:])
        sv = s_.get(ts, np.nan); lv = l_.get(ts, np.nan)
        if pd.isna(sv) or pd.isna(lv):
            reg[d] = md; continue
        s = bool(sv > lv); stk = stk + 1 if s == ss else 1; ss = s
        if stk >= cf and md != s:
            md = s
        reg[d] = md
    return reg


def bt(reg, sub):
    t = TurboSimulator({d: ar[d] for d in sub}, sub, prices, overheat_w=0.2)
    t._use_overlay = True; t._use_stored_growth = True
    for d in sub:
        tks = t._preextracted[d][0]; fd = {x['ticker']: x for x in ar[d]}
        t._overlay_pre[d] = np.array([0.2 * (fd[tk].get('overheat_pen') or 0) + 0.05 * (fd[tk].get('mom_10_z') or 0)
                                      + 0.06 * (fd[tk].get('vol_low_z') or 0) - 0.3 * (fd[tk].get('recent_ca') or 0) for tk in tks])
    t._cached_key = None; t._ensure_cache(0.15, 0.0, 0.55, 0.30, 0.4, 20, '12m', *G3[:3], *G3[3:])
    flat = list(t._cached_flat)
    r = _run_regime_inner(flat, flat, 0, 6, 3, 3, 6, 3, reg, sub, t._price_arr, t._bench_arr, t._has_bench,
                          t._date_row_indices, len(sub), None, None, None, None,
                          stop_loss_o=None, trailing_stop_o=None, stop_loss_d=None, trailing_stop_d=None)
    return r.get('calmar', 0)


if __name__ == '__main__':
    combos = [(15, 60, 5), (20, 80, 5), (20, 100, 5), (25, 80, 5), (20, 80, 7), (30, 90, 5)]
    blocks = [('19-21', '20190102', '20211231'), ('약세22-23', '20220101', '20231231'), ('24-26', '20240101', '20261231')]
    for nm, idx in [('현행 코스피', kc), ('전종목 동일가중', ew)]:
        vals = [bt(reg_idx(idx, s, l, c, days), days) for s, l, c in combos]
        wf = [bt(reg_idx(idx, 20, 80, 5, days), [d for d in days if a <= d <= b]) for _, a, b in blocks]
        print(f"{nm}: 6설정평균 {np.mean(vals):.3f} CV {np.std(vals)/np.mean(vals):.3f} 최소 {min(vals):.3f} | "
              + " ".join(f"{blocks[i][0]} {wf[i]:.2f}" for i in range(3)))
