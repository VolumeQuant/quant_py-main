"""표본 5개 + 정상 5개 metadata 단계별 비교"""
import sys, json, os
sys.stdout.reconfigure(encoding='utf-8')

# 결손 일자 (state_verify_sample/ 에서)
SAMPLES_BAD = ['20181029','20200319','20221013','20240805','20260102']
# 정상 일자 (state/에서, 최근 정상 5개)
SAMPLES_OK = ['20260507','20260508','20260511','20260512','20260430']

def load_meta(fp):
    if not os.path.exists(fp): return None
    r = json.load(open(fp, encoding='utf-8'))
    m = r.get('metadata', {})
    return {
        'date': r.get('date'),
        'final': len(r.get('rankings', [])),
        'universe': m.get('universe_count'),
        'scored': m.get('scored_count'),
        'ma120_passed': m.get('ma120_passed'),
        'ma120_failed_n': len(m.get('ma120_failed', [])),
    }

print(f'{"일자":<12}{"final":>6}{"universe":>10}{"scored":>8}{"ma120_passed":>14}{"ma120_failed":>14}')
print('-'*70)
print('=== 결손 일자 (state_verify_sample/) ===')
for d in SAMPLES_BAD:
    fp = f'C:/dev/state_verify_sample/ranking_{d}.json'
    m = load_meta(fp)
    if m: print(f'{d:<12}{m["final"]:>6}{m["universe"]:>10}{m["scored"]:>8}{m["ma120_passed"]:>14}{m["ma120_failed_n"]:>14}')

print('\n=== 정상 일자 (state/) ===')
for d in SAMPLES_OK:
    fp = f'C:/dev/state/ranking_{d}.json'
    m = load_meta(fp)
    if m: print(f'{d:<12}{m["final"]:>6}{m["universe"]:>10}{m["scored"]:>8}{m["ma120_passed"]:>14}{m["ma120_failed_n"]:>14}')

# 단계별 비교 — 어디서 줄어드는지
print('\n=== 단계별 통과율 (final/universe) ===')
for label, dates, base in [('결손', SAMPLES_BAD, 'state_verify_sample'), ('정상', SAMPLES_OK, 'state')]:
    print(f'  [{label}]')
    for d in dates:
        fp = f'C:/dev/{base}/ranking_{d}.json'
        m = load_meta(fp)
        if not m or not m['universe']: continue
        u, s, p, f = m['universe'], m['scored'], m['ma120_passed'], m['final']
        print(f'    {d}: universe→ma120={p}/{u} ({100*p/u:.0f}%), ma120→scored={s}/{p} ({100*s/p:.0f}% if p>0), final={f}')
