# -*- coding: utf-8 -*-
"""KSIC(DART 표준산업분류) 기반 섹터맵 수집 → data_cache/ksic_sector_map.parquet.

KRX 24개 대분류 업종(의료·정밀기기에 반도체검사장비/카메라부품/실제의료기기 혼재)이
부정확해서, DART induty_code(5자리 KSIC)로 정확한 표시섹터를 만든다.
induty_code는 거의 정적이라 1회 수집 후 증분(신규 종목만). 표시 전용, 매매 무관.

사용:
  python refresh_ksic_sector.py            # 증분 (캐시 없는 종목만)
  python refresh_ksic_sector.py --sample   # 표본(top20+α) 검증
  python refresh_ksic_sector.py --rebuild   # 전량 재수집
"""
import sys, io, time, re, os, glob, argparse
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import pandas as pd
import OpenDartReader

CACHE = 'data_cache/ksic_sector_map.parquet'


def _dart_key():
    return re.search(r'DART_API_KEY\s*=\s*["\']([0-9a-f]{40})',
                     open('config.py', encoding='utf-8').read()).group(1)


def universe_tickers():
    """최신 krx_sector 캐시의 종목코드 = universe 상한."""
    f = sorted(glob.glob('data_cache/krx_sector_*.parquet'))[-1]
    df = pd.read_parquet(f)
    return [str(t).zfill(6) for t in df['종목코드']], f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sample', action='store_true')
    ap.add_argument('--rebuild', action='store_true')
    args = ap.parse_args()

    if args.sample:
        tickers = ['080220','000660','187870','005930','219130','031330','049630',
                   '131290','025560','043260','356860','452280','037460','161390',
                   '089970','007810','382800','053610','281820','067310','041830']
        src = 'sample'
    else:
        tickers, src = universe_tickers()
    print(f'[universe] {len(tickers)}종목 ({src})')

    have = {}
    if os.path.exists(CACHE) and not args.rebuild and not args.sample:
        old = pd.read_parquet(CACHE)
        have = dict(zip(old['ticker'].astype(str).str.zfill(6), old['induty_code']))
        print(f'[cache] 기존 {len(have)}종목 → 신규만 수집')

    todo = [t for t in tickers if t not in have]
    print(f'[fetch] {len(todo)}종목 DART 조회 (예상 {len(todo)*0.4/60:.1f}분)')

    dart = OpenDartReader(_dart_key())
    rows = dict(have)
    for i, t in enumerate(todo, 1):
        try:
            c = dart.company(t)
            rows[t] = c.get('induty_code')
        except Exception as e:
            rows[t] = None
        if i % 200 == 0:
            print(f'  ...{i}/{len(todo)}')
        time.sleep(0.35)

    out = pd.DataFrame([(t, v) for t, v in rows.items()], columns=['ticker', 'induty_code'])
    if not args.sample:
        out.to_parquet(CACHE, index=False)
        print(f'[save] {CACHE} ({len(out)}종목)')

    # 검증: 표시섹터 분포
    sys.path.insert(0, 'backtest')
    from fast_generate_rankings_v2 import ksic_to_sector
    out['표시섹터'] = out['induty_code'].map(ksic_to_sector)
    print('\n[표시섹터 분포]')
    print(out['표시섹터'].value_counts(dropna=False).to_string())
    if args.sample:
        names = {'080220':'제주반도체','000660':'SK하이닉스','187870':'디바이스','005930':'삼성전자','219130':'타이거일렉','031330':'에스에이엠티','049630':'재영솔루텍','131290':'티에스이','025560':'미래산업','043260':'성호전자','356860':'티엘비','452280':'한선엔지니어링','037460':'삼지전자','161390':'한국타이어','089970':'브이엠','007810':'코리아써키트','382800':'지앤비에스에코','053610':'프로텍','281820':'케이씨텍','067310':'하나마이크론','041830':'인바디'}
        print('\n[표본 검증]')
        for _, r in out.iterrows():
            print(f"  {names.get(r['ticker'],'?'):<12}({r['ticker']}) KSIC {str(r['induty_code']):<6} → {r['표시섹터']}")


if __name__ == '__main__':
    main()
