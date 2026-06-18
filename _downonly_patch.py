# -*- coding: utf-8 -*-
"""committed 공식 state(both penalty)를 down-only로 외과수술 패치 — 데이터 드리프트 0.
병합(up전용) 페널티만 제거: recent_ca=1인데 최근K영업일내 down-CA 없으면 → score +0.3, recent_ca 삭제, composite 재랭킹.
그 후 전 날짜 wr 재계산(date순, down-only composite 체인). defense는 페널티 없어 무변경."""
import sys, os, io, glob, json
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import run_daily as rd
W = 0.3; K = 126
DC = os.path.join(str(rd.SCRIPT_DIR), 'data_cache')
ca_down = json.load(open(os.path.join(DC, 'ca_events.json'), encoding='utf-8'))['ca_by_ticker']
files = sorted(glob.glob('state/ranking_*.json'))
days = [os.path.basename(f)[8:16] for f in files if os.path.basename(f)[8:16].isdigit() and len(os.path.basename(f)[8:16]) == 8]
days = sorted(days)
idx = {d: i for i, d in enumerate(days)}
def down_trig(tk, d):
    ii = idx[d]; cut = days[max(0, ii - K)]
    ds = ca_down.get(tk)
    return bool(ds and any(cut < e <= d for e in ds))
# 1) composite 패치
n_removed = 0; n_days_changed = 0
for d in days:
    p = f'state/ranking_{d}.json'
    obj = json.load(open(p, encoding='utf-8')); rk = obj['rankings']
    changed = False
    for x in rk:
        if x.get('recent_ca'):  # both-direction 페널티 발동중
            if not down_trig(x['ticker'], d):  # down-CA 없음 = up전용(병합) → 해제
                x['score'] = round(x.get('score', 0) + W, 4)
                x.pop('recent_ca', None)
                n_removed += 1; changed = True
    if changed:
        rk2 = sorted(rk, key=lambda z: -z.get('score', -99))
        for i, x in enumerate(rk2, 1):
            x['composite_rank'] = i
        obj['rankings'] = rk2
        json.dump(obj, open(p, 'w', encoding='utf-8'), ensure_ascii=False)
        n_days_changed += 1
print(f"composite 패치: 병합페널티 해제 {n_removed} 종목-일, 변경된 날 {n_days_changed}/{len(days)}")
# 2) wr 재계산 (date순)
class _L:
    def write(self, *a): pass
    def flush(self): pass
ok = 0
for d in days:
    if rd._postprocess_ranking(d, 'state', 'boost', _L()): ok += 1
print(f"wr 재계산: {ok}/{len(days)}")
print("→ defense 무변경(페널티 없음). 검증: _verify_do.py state")
