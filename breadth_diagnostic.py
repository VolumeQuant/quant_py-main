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
# ★비대칭 확인일 (2026-06-20): 발동 빠르게(3) / 복귀 신중하게(5).
# 복귀 3일은 국면의존(약세·협소 유리·코로나 불리)·표본얇아 중간신뢰 → 5일로 보수화(사용자 결정).
# 7.4년 검증: 3/5 Calmar 4.280(3/3 4.358과 노이즈내), 전환 32→26↓, 코로나서 덜다침.
CONFIRM_FIRE = 3
CONFIRM_RECOVER = 5
CONFIRM = CONFIRM_FIRE  # 호환
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
    b = ((sdf > ma) & valid).sum(axis=1) / valid.sum(axis=1).replace(0, np.nan)
    # ★거래일만 (all_ohlcv_adj는 주말 carry 포함 → 3일확인이 달력일 카운트되는 버그).
    # kospi_yf(거래일만)로 reindex해 BT(거래일 기준)와 정합. 2026-06-20 사용자 지적 fix.
    try:
        kidx = pd.read_parquet(os.path.join(CACHE, 'kospi_yf.parquet')).index
        b = b.reindex(kidx).dropna()
    except Exception:
        b = b[b.index.dayofweek < 5]  # 폴백: 주말만 제거
    return b


def true_breadth():
    """진짜 시장 참여폭 — 전종목 중 자기 200일선 위 비율(섹터지수 착시 보정).
    섹터'지수'는 연초급등 잔상으로 속이 병들어도 위로 보임(바이오 +33%인데 내부 8%) → 종목기준이 정직.
    returns (pct, healthy_sector). 실패시 (None, '')."""
    try:
        prices = pd.read_parquet(sorted(glob.glob(os.path.join(CACHE, 'all_ohlcv_adj_*.parquet')))[-1]).replace(0, np.nan)
        ma = prices.rolling(200, min_periods=150).mean()
        valid = prices.notna() & ma.notna()
        pct = float(((prices > ma) & valid).iloc[-1].sum() / valid.iloc[-1].sum())
        # 내부breadth 가장 건강한 섹터 1개
        sec = pd.read_parquet(sorted(glob.glob(os.path.join(CACHE, 'krx_sector_*.parquet')))[-1])
        sec = sec.rename(columns={sec.columns[0]: 'ticker', sec.columns[1]: 'sector'})
        best = ('', 0)
        for s, g in sec.groupby('sector')['ticker']:
            cols = [t for t in g if t in valid.columns and valid[t].iloc[-1]]
            if len(cols) < 5: continue
            w = sum(1 for t in cols if (prices[t] > ma[t]).iloc[-1]) / len(cols)
            if w > best[1]: best = (s, w)
        return pct, f"{best[0]}({best[1]*100:.0f}%)"
    except Exception:
        return None, ''


def sector_breadth_status():
    """섹터지수 브레드스(트리거용) + 3일확인 발동여부 + 전일대비 전환(발동/복귀 알림용)."""
    bs = _sector_breadth_series().dropna()
    cur = float(bs.iloc[-1])
    # ★비대칭: 발동 CONFIRM_FIRE(3)일 아래, 복귀 CONFIRM_RECOVER(5)일 위
    md = True; below = 0; above = 0
    state_hist = []  # 각 날의 발동여부(not md) 기록 → 마지막 2일로 전환 감지
    for v in bs.values:
        if v < THRESH: below += 1; above = 0
        else: above += 1; below = 0
        if md and below >= CONFIRM_FIRE: md = False        # 발동
        elif (not md) and above >= CONFIRM_RECOVER: md = True  # 복귀
        state_hist.append(not md)  # True=방어발동
    defense_on = state_hist[-1]
    defense_prev = state_hist[-2] if len(state_hist) >= 2 else defense_on
    below = 0
    for v in bs.values[::-1]:
        if v < THRESH:
            below += 1
        else:
            break
    return {'value': cur, 'defense_on': defense_on, 'hist_mean': float(bs.mean()),
            'streak_below': below, 'date': str(bs.index[-1].date()),
            'just_fired': (defense_on and not defense_prev),       # 오늘 막 발동
            'just_recovered': (not defense_on and defense_prev)}   # 오늘 막 복귀


def breadth_scale_by_date(dates):
    """각 date의 노출 스케일 {date_str: 1.0(정상) or SCALE(0.5, 브레드스 발동)}.
    3일확인 상태머신을 전체 시계열에 적용(BT와 동일). 킬스위치/실패시 전부 1.0(무영향).
    calc_system_returns·run_daily 공용 — production==BT 정합용."""
    if os.environ.get('REGIME_BREADTH_DISABLE') == '1':
        return {d: 1.0 for d in dates}
    try:
        bs = _sector_breadth_series().dropna()
        # ★비대칭 상태머신(발동 3일/복귀 5일) → date별 defense여부 (BT==production)
        defmap = {}
        md = True; below = 0; above = 0
        for ts, v in bs.items():
            if v < THRESH: below += 1; above = 0
            else: above += 1; below = 0
            if md and below >= CONFIRM_FIRE: md = False
            elif (not md) and above >= CONFIRM_RECOVER: md = True
            defmap[ts.strftime('%Y%m%d')] = (not md)  # True=브레드스 방어(축소)
        out = {}
        for d in dates:
            ds = d if (isinstance(d, str) and len(d) == 8) else pd.Timestamp(d).strftime('%Y%m%d')
            out[d] = SCALE if defmap.get(ds, False) else 1.0
        return out
    except Exception:
        return {d: 1.0 for d in dates}


def build_breadth_advisory():
    """텔레그램용 — (문구, is_alert) 반환. is_alert(발동/지속/복귀=행동필요)면 메시지 상단,
    평소(정상/감시/협소)면 footer 배치용. 아이콘은 상태표시 1개(🚨🟠✅🟢🟡🔴)만 — 장식 기호 안 씀.
    문구는 쉬운 말(전문용어/BT숫자 뺌). head_pct=종목기준(전체 종목 중 200일선 위 비율=상승추세)."""
    if os.environ.get('REGIME_BREADTH_DISABLE') == '1':
        return '', False
    try:
        s = sector_breadth_status()
        tb, _best = true_breadth()  # 종목기준 참여폭(전체 종목 중 200일선 위 비율 = 상승추세)
        head_pct = (tb * 100) if tb is not None else s['value'] * 100
        note = "  ※ 종목 신호는 그대로, 비중만 조절"  # 짧게(폰 1줄)
        if s.get('just_recovered'):
            return (f"✅ <b>방어 해제 — 주식 100% 복귀 OK</b>\n"
                    f"  상승 추세 종목 {head_pct:.0f}%로 회복", True)
        if s.get('just_fired'):
            return (f"🚨 <b>시장 방어 — 주식 50% 현금화 권고</b>\n"
                    f"  상승 추세 종목 {head_pct:.0f}%뿐 (대부분 약세)\n{note}", True)
        if s['defense_on']:
            return (f"🟠 <b>방어 지속 — 현금 50% 유지</b> ({s['streak_below']}일째)\n"
                    f"  상승 추세 종목 {head_pct:.0f}%\n{note}", True)
        if head_pct < 30:
            return (f"🔴 상승 추세 종목 {head_pct:.0f}%뿐 — 소수만 강세\n"
                    f"  3일 지속 시 비중 절반 권고 (아직 아님)", False)
        if head_pct < 45:
            return (f"🟡 상승 추세 종목 {head_pct:.0f}% — 약화(감시 중)", False)
        return (f"🟢 상승 추세 종목 {head_pct:.0f}% — 정상", False)
    except Exception:
        return '', False


def build_breadth_line():
    """하위호환 — 문구만 반환(위치 무관 호출처용)."""
    return build_breadth_advisory()[0]


if __name__ == '__main__':
    import io, sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    s = sector_breadth_status()
    print(f"[{s['date']}] 섹터브레드스 {s['value']*100:.1f}% (평균 {s['hist_mean']*100:.0f}%) "
          f"| 발동={s['defense_on']} | <35% 연속 {s['streak_below']}일")
    print("\n--- 푸터 미리보기 ---")
    print(build_breadth_line())
