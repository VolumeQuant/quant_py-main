# -*- coding: utf-8 -*-
"""신규진입 검문소 (2026-07-05) — 개인봇 전용 정보 리포트, 매매신호 불변.

목적: 사용자가 top20 신규 진입/순위 급등 종목을 매번 수동 검색하던 것을 자동화.
디바이스·선익·삼지 유형(가짜 순위) 재발 감시 — 필터가 쓰는 것과 동일한 진단값으로.

대상:
  1) 신규 매수권: 오늘 picks 중 어제 cr-rank 3위 밖이었던 종목
  2) top20 신규: 오늘 cr top20에 있는데 어제 top20에 없던 종목
  3) 순위 급등: 오늘 top20 & 어제 대비 cr 10계단 이상 상승

건강 진단 (ranking JSON 저장값 기반, FG 필터와 동일 수치):
  - lump_mm: 최근 4분기 매출 min/max (0.25 미만 = lumpiness 페널티 발동중, 디바이스형)
  - accr_b/accr_c: 현금 없는 이익 / 분기쏠림 (B 25 초과 & C 0.7 초과 = accruals 발동, 삼지형)
  - 페널티 역산: growth_s ÷ 이론G 비율로 발동 여부 교차확인 (구파일 폴백)
  - recent_ca / overheat_pen / 순위 궤적 속도 (3일내 30계단 급행 = 🚨)

킬스위치: env ENTRY_SENTINEL_DISABLE=1. 실패 시 호출부에서 무시 (메시지 발송 영향 0).
★개인봇 전용 — 채널 발송 금지 (호출부에서 PRIVATE_CHAT_ID 없으면 스킵).
"""
import os
import glob
import json
from pathlib import Path

TRAJ_DAYS = 8          # 궤적 표시 일수
SURGE_STEPS = 10       # '급등' 판정: 어제 대비 cr 상승폭
EXPRESS_FROM = 30      # '급행' 판정: 3일 전 이 순위 밖 → 오늘 top10
ABSENT = 99            # 랭킹(저장 top~65) 밖


def _cr_int_map(ranking_dict):
    """저장 rankings → {ticker: 당일 cr 정수순위(1..N)}"""
    if not ranking_dict:
        return {}
    rlist = ranking_dict.get('rankings', [])
    by_cr = sorted(rlist, key=lambda r: r.get('composite_rank', 999))
    return {r['ticker']: i + 1 for i, r in enumerate(by_cr)}


def _load_history_maps(state_dir, upto_date, n=TRAJ_DAYS):
    """state에서 upto_date 이하 최근 n일 (date, cr_int_map) 리스트 (과거→최근)."""
    files = sorted(glob.glob(str(Path(state_dir) / 'ranking_*.json')))
    out = []
    for fp in reversed(files):
        d = os.path.basename(fp)[8:16]
        if not (d.isdigit() and len(d) == 8 and d <= upto_date):
            continue
        try:
            data = json.load(open(fp, encoding='utf-8'))
            out.append((d, _cr_int_map(data)))
        except Exception:
            continue
        if len(out) >= n:
            break
    return list(reversed(out))


def _penalty_forensic(item):
    """growth_s ÷ 이론G(0.4rev+0.4oca+0.2gp) 비율 — 페널티 발동 역산 (구파일 폴백용).
    무페널티 기준선이 ~1.12라 정규화 후 판정."""
    g = item.get('growth_s')
    rev = item.get('rev_z') or 0
    oca = item.get('oca_z') or 0
    gp = item.get('gp_growth_z') or 0
    implied = 0.4 * rev + 0.4 * oca + 0.2 * gp
    if g is None or abs(implied) < 0.05:
        return None
    r = (g / implied) / 1.12
    if 0.20 <= r <= 0.28:
        return 'accruals 페널티 발동중(×0.24)'
    if 0.28 < r <= 0.34:
        return 'lumpiness 페널티 발동중(×0.3)'
    if 0.60 <= r <= 0.78:
        return 'QoQ 페널티(×0.7)'
    return None


def _health_lines(item, reentry_wait=None):
    """종목 건강 진단 줄들 — 저장 진단값 우선, 없으면 역산 폴백."""
    lines = []
    flags = 0
    mm = item.get('lump_mm')
    if mm is not None:
        if mm < 0.25:
            lines.append(f'🚨 매출 분기쏠림 {mm:.2f} — lumpiness 발동중 (디바이스형)')
            flags += 1
        elif mm < 0.35:
            lines.append(f'⚠️ 매출 분기쏠림 경계 {mm:.2f} (0.25 미만이면 발동)')
            flags += 1
        else:
            lines.append(f'매출 고름 {mm:.2f} ✅')
    b = item.get('accr_b')
    c = item.get('accr_c')
    if b is not None and c is not None:
        if b > 25 and c > 0.7:
            lines.append(f'🚨 이익의 질 B{b:.0f}/C{c:.2f} — accruals 발동중 (삼지형)')
            flags += 1
        elif b > 18:
            lines.append(f'⚠️ 이익-현금 괴리 경계 B{b:.0f} (25 초과+쏠림이면 발동)')
            flags += 1
        else:
            lines.append(f'이익 질 양호 B{b:.0f}/C{c:.2f} ✅')
    if mm is None and b is None:
        fx = _penalty_forensic(item)
        if fx:
            lines.append(f'⚠️ {fx}')
            flags += 1
        else:
            lines.append('재무진단값 미저장(구파일) — 페널티 역산상 무발동 ✅')
    if item.get('recent_ca'):
        lines.append('⚠️ 최근 무상증자/분할 이력 — CA 페널티 감점중')
        flags += 1
    op = item.get('overheat_pen')
    if op is not None and op < -1.0:
        lines.append(f'⚠️ 밸류 과열 감점중 (pen {op:.1f})')
        flags += 1
    if reentry_wait and item.get('ticker') in reentry_wait:
        d = reentry_wait[item['ticker']].get('days')
        lines.append(f'🔁 재진입 쿨다운 대기 {d}일 (최근 시스템 매도)')
    return lines, flags


def _traj_str(ticker, hist_maps):
    seq = []
    for _, m in hist_maps:
        r = m.get(ticker)
        seq.append(str(r) if r else '·')
    # 급행 판정: 3거래일 전 EXPRESS_FROM 밖(또는 부재) → 오늘 top10
    express = False
    if len(hist_maps) >= 4:
        r3 = hist_maps[-4][1].get(ticker, ABSENT)
        r0 = hist_maps[-1][1].get(ticker, ABSENT)
        if r3 > EXPRESS_FROM and r0 <= 10:
            express = True
    return '→'.join(seq), express


def alpha_decay_lines(equity_history, windows=(60, 120)):
    """알파 부식 감시 — 최근 N일 수익률이 7.4년 역사 분포에서 몇 분위인지.
    하위 5% 미만 🚨 / 15% 미만 ⚠️. returns (lines, alert_bool)."""
    if not equity_history or len(equity_history) < 300:
        return [], False
    ds = sorted(equity_history)
    eq = [float(equity_history[d]) for d in ds]
    lines = []
    alert = False
    for w in windows:
        if len(eq) <= w + 20:
            continue
        rolls = [eq[i] / eq[i - w] - 1 for i in range(w, len(eq)) if eq[i - w] > 0]
        cur = rolls[-1]
        hist = sorted(rolls[:-1])
        # 백분위 (0~100)
        import bisect
        pct = bisect.bisect_left(hist, cur) / len(hist) * 100
        if pct < 5:
            lines.append(f'🚨 알파 부식 의심: 최근 {w}일 {cur*100:+.1f}% = 역사 하위 {pct:.0f}% — 전략/데이터 점검 필요')
            alert = True
        elif pct < 15:
            lines.append(f'⚠️ 알파 감시: 최근 {w}일 {cur*100:+.1f}% = 역사 하위 {pct:.0f}%')
            alert = True
        else:
            lines.append(f'알파 건강: 최근 {w}일 {cur*100:+.1f}% (역사 {pct:.0f}분위) ✅')
    return lines, alert


def build_sentinel_message(rankings_t0, rankings_t1, picks=None,
                           reentry_wait=None, state_dir=None,
                           system_returns=None):
    """개인봇용 검문소 메시지. 대상 종목 없고 부식 경보도 없으면 None."""
    if os.environ.get('ENTRY_SENTINEL_DISABLE') == '1':
        return None
    if not rankings_t0 or not rankings_t1:
        return None
    state_dir = state_dir or (Path(__file__).parent / 'state')
    date0 = rankings_t0.get('date', '')
    m0 = _cr_int_map(rankings_t0)
    m1 = _cr_int_map(rankings_t1)
    items0 = {r['ticker']: r for r in rankings_t0.get('rankings', [])}
    hist = _load_history_maps(state_dir, date0.replace('-', '')[:8] or '99999999')

    top20_now = {t for t, r in m0.items() if r <= 20}
    top20_prev = {t for t, r in m1.items() if r <= 20}
    pick_tks = [p['ticker'] for p in (picks or [])]

    targets = []  # (ticker, 라벨)
    seen = set()
    for t in pick_tks:
        if m1.get(t, ABSENT) > 3 and t not in seen:
            targets.append((t, '🛒 신규 매수권'))
            seen.add(t)
    for t in sorted(top20_now - top20_prev, key=lambda x: m0.get(x, ABSENT)):
        if t not in seen:
            targets.append((t, '🆕 top20 신규'))
            seen.add(t)
    for t in sorted(top20_now & top20_prev, key=lambda x: m0.get(x, ABSENT)):
        if t in seen:
            continue
        if (m1.get(t, ABSENT) - m0.get(t, ABSENT)) >= SURGE_STEPS:
            targets.append((t, f'📈 급등 {m1.get(t)}→{m0.get(t)}위'))
            seen.add(t)

    decay_lines, decay_alert = alpha_decay_lines(
        (system_returns or {}).get('equity_history') or {})

    if not targets and not decay_alert:
        return None

    lines = [f'🔍 <b>신규진입 검문소</b> ({date0})',
             '매매신호와 무관한 참고 정보입니다.', '']
    total_flags = 0
    for t, label in targets:
        it = items0.get(t)
        if not it:
            continue
        nm = it.get('name', t)
        sec = it.get('sector', '기타')
        per = it.get('per'); pbr = it.get('pbr'); roe = it.get('roe')
        val = ' · '.join(x for x in [
            f'PER {per:.0f}' if per else '',
            f'PBR {pbr:.1f}' if pbr else '',
            f'ROE {roe:.0f}%' if roe else ''] if x)
        traj, express = _traj_str(t, hist)
        lines.append(f'<b>{label} — {nm}({t}) · {sec}</b>')
        if val:
            lines.append(f'{val}')
        lines.append(f'궤적 {traj}' + (' 🚨3일내 급행 — 순위 급조 의심, 주의' if express else ''))
        if express:
            total_flags += 1
        h, fl = _health_lines(it, reentry_wait)
        lines.extend(h)
        total_flags += fl
        lines.append('')
    lines.append(f'경고 플래그 합계: {total_flags}개'
                 + (' — 이상 없음' if total_flags == 0 else ' — 위 ⚠️/🚨 항목 확인 권장'))
    # 필터 생존 모니터 (6/18형 '조용한 필터 사망' 감지): 오늘 랭킹 내 페널티 발동 수
    pen_cnt = 0
    for it in rankings_t0.get('rankings', []):
        mm = it.get('lump_mm'); b = it.get('accr_b'); c = it.get('accr_c')
        if (mm is not None and mm < 0.25) or (b is not None and c is not None and b > 25 and c > 0.7):
            pen_cnt += 1
        elif mm is None and b is None and _penalty_forensic(it):
            pen_cnt += 1
    lines.append(f'필터 발동 현황: 상위권 {pen_cnt}종목 감점중'
                 + (' ⚠️ 0이면 필터 사망 의심 — 점검 필요' if pen_cnt == 0 else ' (필터 정상 작동)'))
    if decay_lines:
        lines.append('')
        lines.extend(decay_lines)
    return '\n'.join(lines)


if __name__ == '__main__':
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    R = Path(__file__).parent
    files = sorted(glob.glob(str(R / 'state' / 'ranking_*.json')))
    valid = [f for f in files if os.path.basename(f)[8:16].isdigit()]
    t0 = json.load(open(valid[-1], encoding='utf-8'))
    t1 = json.load(open(valid[-2], encoding='utf-8'))
    picks = [{'ticker': r['ticker']} for r in sorted(t0['rankings'], key=lambda x: x.get('weighted_rank', 99))[:3]]
    msg = build_sentinel_message(t0, t1, picks=picks, state_dir=R / 'state')
    print(msg if msg else '(대상 종목 없음)')
