# -*- coding: utf-8 -*-
"""시장폭(브레드스) 진단지표 — 표시 전용, 매매 무관 (2026-06-20 자율주행 산출물).
조기위험탐지 BT 결론: 브레드스는 게이트로는 실패(EARLY_WARNING_FINDINGS_2026_06_20.md),
단 '내 보유리더 vs 시장 전체 폭' 상황인지용 진단지표로는 가치. NAV디스카운트·국면조기경보처럼 정보성.

★배포 안 됨(자율정책). 복귀 후 승인 시 send_telegram_auto.py 푸터에 build_breadth_line() 호출로 붙임.
매매 로직 절대 무변경.

지표:
- b200 = 유니버스 중 (종가 > 자기 MA200) 비율. 시장 참여폭. 낮을수록 광범위 약세.
- HL   = (52주 신고가 종목수 - 신저가 종목수) / 유니버스. 음수=신저가 우세=폭 붕괴.
- 둘 다 PIT(해당일까지 데이터만), 전종목 수정주가 기반.
"""
import glob, os
import numpy as np, pandas as pd

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data_cache')


def compute_breadth(as_of=None, ohlcv_path=None):
    """as_of(YYYYMMDD, None=최신)까지 PIT. returns dict(b200, b50, hl, b200_pct, hist_mean)."""
    if ohlcv_path is None:
        ohlcv_path = sorted(glob.glob(os.path.join(CACHE, 'all_ohlcv_adj_*.parquet')))[-1]
    px = pd.read_parquet(ohlcv_path).replace(0, np.nan)
    if as_of:
        ts = pd.Timestamp(f"{as_of[:4]}-{as_of[4:6]}-{as_of[6:]}")
        px = px.loc[px.index <= ts]
    ma200 = px.rolling(200, min_periods=150).mean()
    ma50 = px.rolling(50, min_periods=40).mean()
    hi252 = px.rolling(252, min_periods=200).max()
    lo252 = px.rolling(252, min_periods=200).min()
    v200 = ma200.notna() & px.notna(); v50 = ma50.notna() & px.notna()
    vhl = hi252.notna() & px.notna()
    b200 = (((px > ma200) & v200).sum(axis=1) / v200.sum(axis=1).replace(0, np.nan))
    b50 = (((px > ma50) & v50).sum(axis=1) / v50.sum(axis=1).replace(0, np.nan))
    nh = ((px >= hi252) & vhl).sum(axis=1); nl = ((px <= lo252) & vhl).sum(axis=1)
    hl = (nh - nl) / vhl.sum(axis=1).replace(0, np.nan)
    cur_b200 = float(b200.iloc[-1]); cur_b50 = float(b50.iloc[-1]); cur_hl = float(hl.iloc[-1])
    hist = b200.dropna()
    pct = float((hist < cur_b200).mean() * 100)  # 현재 b200의 역사적 백분위
    return {'b200': cur_b200, 'b50': cur_b50, 'hl': cur_hl,
            'b200_pct': pct, 'hist_mean': float(hist.mean()), 'date': str(px.index[-1].date())}


def build_breadth_line(as_of=None):
    """텔레그램 푸터용 표시 문자열(HTML). 매매신호 아님, 정보 전용."""
    try:
        b = compute_breadth(as_of)
        b200p = b['b200'] * 100; meanp = b['hist_mean'] * 100; hlp = b['hl'] * 100
        # 상태 이모지: 시장폭 강/중/약
        if b['b200_pct'] >= 60:
            tag = '🟢 시장폭 양호'
        elif b['b200_pct'] >= 30:
            tag = '🟡 시장폭 보통'
        else:
            tag = '🔴 시장폭 위축(소형주 약세)'
        lines = [
            f"📐 시장폭(참여도): {tag}",
            f"  · 200일선 위 종목 {b200p:.0f}% (평균 {meanp:.0f}%, 하위 {b['b200_pct']:.0f}%)",
            f"  · 신고가-신저가 {hlp:+.0f}%",
            f"  ※ 정보용. 약세는 주로 소형주 — 시스템은 시총·추세필터로 약한 소형주 미보유.",
        ]
        return '\n'.join(lines)
    except Exception as e:
        return ''  # 실패해도 메시지 안 깨짐


if __name__ == '__main__':
    import io, sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    b = compute_breadth()
    print(f"[{b['date']}] b200={b['b200']*100:.1f}% (평균 {b['hist_mean']*100:.0f}%, 하위 {b['b200_pct']:.0f}%) "
          f"| b50={b['b50']*100:.1f}% | HL={b['hl']*100:+.1f}%")
    print("\n--- 텔레그램 표시 미리보기 ---")
    print(build_breadth_line())
