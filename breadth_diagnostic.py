# -*- coding: utf-8 -*-
"""섹터 브레드스 조기방어 advisory — US 위너 KR재현 (2026-06-20 배포).
US 최종추천: 저정밀 브레드스 신호는 binary금지 → 노출 50% 축소(scale). KR 집중도 더 심해 필수.
검증(research/EARLY_WARNING_FINDINGS_2026_06_20.md): 섹터브레드스<35%/3일 발동시 노출 50%축소
→ Calmar 4.08→4.36, MDD 25.9→24.0%, 약세 24.7→19.2%, leave-one-bear-out 우위유지.

★시스템은 시그널·사이징 분리(현금버퍼=사용자 meta)라 이 신호는 '노출 50% 축소 권고' advisory.
매매 시그널(3종목)은 불변. 사용자가 현금버퍼로 노출 조절(예: 100→50% 또는 평소 80/20→40/60).
킬스위치: REGIME_BREADTH_DISABLE=1. 수집실패시 안전 폴백(advisory 미표시, 매매 무영향).

지표: 23개 KRX섹터 EW지수 중 자기 200DMA 위 비율. <35% 3일확인 = 시장 '속' 붕괴(조기경보).
"""
import glob, os
import numpy as np, pandas as pd

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data_cache')
THRESH = 0.35
CONFIRM = 3
SCALE = 0.5  # 발동시 권고 노출 (50%)


def _sector_breadth_series(ohlcv_path=None, sector_path=None):
    if ohlcv_path is None:
        ohlcv_path = sorted(glob.glob(os.path.join(CACHE, 'all_ohlcv_adj_*.parquet')))[-1]
    if sector_path is None:
        sector_path = sorted(glob.glob(os.path.join(CACHE, 'krx_sector_*.parquet')))[-1]
    prices = pd.read_parquet(ohlcv_path).replace(0, np.nan)
    sec = pd.read_parquet(sector_path)
    sec = sec.rename(columns={sec.columns[0]: 'ticker', sec.columns[1]: 'sector'})
    ret = prices.pct_change(fill_method=None)
    idx = {}
    for s, g in sec.groupby('sector')['ticker']:
        cols = [t for t in g if t in ret.columns]
        if len(cols) >= 5:
            idx[s] = (1 + ret[cols].mean(axis=1).fillna(0)).cumprod()
    sdf = pd.DataFrame(idx)
    ma = sdf.rolling(200, min_periods=150).mean()
    valid = sdf.notna() & ma.notna()
    return ((sdf > ma) & valid).sum(axis=1) / valid.sum(axis=1).replace(0, np.nan)


def sector_breadth_status():
    """현재 섹터브레드스 + 3일확인 발동여부. dict(value, defense_on, hist_mean, streak_below)."""
    bs = _sector_breadth_series().dropna()
    cur = float(bs.iloc[-1])
    # 3일확인 상태머신 (BT와 동일)
    md = True; stk = 0; ss = None
    for v in bs.values:
        s = v > THRESH
        stk = stk + 1 if s == ss else 1; ss = s
        if stk >= CONFIRM and md != s:
            md = s
    # 최근 연속 <임계 일수 (카운트다운 표시용)
    below = 0
    for v in bs.values[::-1]:
        if v < THRESH:
            below += 1
        else:
            break
    return {'value': cur, 'defense_on': (not md), 'hist_mean': float(bs.mean()),
            'streak_below': below, 'date': str(bs.index[-1].date())}


def build_breadth_line():
    """텔레그램 푸터용 — 섹터 참여폭 + 발동시 50% 축소 권고. 정보·권고용(매매 시그널 아님)."""
    if os.environ.get('REGIME_BREADTH_DISABLE') == '1':
        return ''
    try:
        s = sector_breadth_status()
        v = s['value'] * 100; mean = s['hist_mean'] * 100
        if s['defense_on']:
            return (f"📐 <b>섹터 참여폭 {v:.0f}%</b> (평균 {mean:.0f}%) — 🔴 광범위 약세\n"
                    f"  ⚠️ 섹터 절반↑ 200일선 붕괴 {s['streak_below']}일 → <b>시스템 노출 50% 축소 권고</b>\n"
                    f"  ※ 보험성(US검증): 약세장 MDD 24.7→19.2%. 현금버퍼로 조절. 매매시그널은 불변.")
        elif v < mean * 0.7:
            return (f"📐 <b>섹터 참여폭 {v:.0f}%</b> (평균 {mean:.0f}%) — 🟡 약화(감시)\n"
                    f"  ※ <35% 3일 지속 시 노출 50% 축소 권고. 아직 미발동.")
        else:
            return f"📐 섹터 참여폭 {v:.0f}% (평균 {mean:.0f}%) — 🟢 정상"
    except Exception:
        return ''


if __name__ == '__main__':
    import io, sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    s = sector_breadth_status()
    print(f"[{s['date']}] 섹터브레드스 {s['value']*100:.1f}% (평균 {s['hist_mean']*100:.0f}%) "
          f"| 발동={s['defense_on']} | <35% 연속 {s['streak_below']}일")
    print("\n--- 푸터 미리보기 ---")
    print(build_breadth_line())
