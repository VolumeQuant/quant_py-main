# -*- coding: utf-8 -*-
"""펌프게이트 배포 마무리 — temp state postprocess(wr 추가) + 검증 + swap.
실행: FG 재생성(state_pump) 완료 후. 단계별 안전(백업 후 swap)."""
import sys, os, glob, json, shutil
sys.path.insert(0,'C:/dev')
import run_daily as RD
BO='C:/dev/state_pump'; DE='C:/dev/state_pump/defense'
def dates_in(d): return sorted(os.path.basename(f)[8:16] for f in glob.glob(d+'/ranking_*.json') if os.path.basename(f)[8:16].isdigit() and len(os.path.basename(f)[8:16])==8)
# 1) postprocess (날짜순, wr 추가)
for tag,d,mode in [('boost',BO,'boost'),('defense',DE,'defense')]:
    ds=dates_in(d); ok=0
    for dt in ds:
        try:
            if RD._postprocess_ranking(dt, d, mode, None): ok+=1
        except Exception as e: print(f'  postprocess 실패 {dt}: {e}')
    print(f'[{tag}] postprocess {ok}/{len(ds)}일 완료',flush=True)
# 2) 검증: 금호 차단 확인 (펌프 발동일) + 종목수 sanity
print('\n[검증] 금호건설(002990) 최근 — 펌프게이트로 차단됐나')
for dt in ['20260625','20260626','20260629']:
    f=BO+f'/ranking_{dt}.json'
    if os.path.exists(f):
        rk=json.load(open(f,encoding='utf-8'))['rankings']
        g=[x for x in rk if x['ticker']=='002990']
        if g: print(f"  {dt}: rank {g[0]['rank']} cr {g[0]['composite_rank']} score {g[0].get('score'):.1f}")
# 종목수 범위 체크
ds=dates_in(BO); cnts=[len(json.load(open(BO+f'/ranking_{d}.json',encoding='utf-8'))['rankings']) for d in ds[::200]]
print(f'\n[검증] boost {len(ds)}일, 종목수 샘플(200일간격): {cnts}')
print('\n→ 이상 없으면 swap 단계 별도 실행 (SWAP=1)')
if os.environ.get('SWAP')=='1':
    # 3) 백업 후 swap (2019+ 만 교체, 2018 파일 유지)
    bak='C:/dev/state_bak_pregate'
    if not os.path.exists(bak):
        shutil.copytree('C:/dev/state', bak, ignore=shutil.ignore_patterns('*.tmp'))
        print(f'[백업] state/ → {bak}')
    for d in dates_in(BO):
        shutil.copy(BO+f'/ranking_{d}.json', f'C:/dev/state/ranking_{d}.json')
    os.makedirs('C:/dev/state/defense',exist_ok=True)
    for d in dates_in(DE):
        shutil.copy(DE+f'/ranking_{d}.json', f'C:/dev/state/defense/ranking_{d}.json')
    print('[SWAP 완료] state/ + state/defense/ 갱신')
