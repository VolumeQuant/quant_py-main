"""NAV 디스카운트 모듈 — 산업지주사 별도 트랙 (Phase C).

매일 자동 갱신:
1. 자회사 시가 (market_cap_ALL_*.parquet)
2. 디스카운트 계산
3. state/nav_discount.json 저장

자회사 지분율 = 분기 캐시 (_phase_c_subs_v2.csv, 분기 1회 갱신)
production 매매 신호 영향 없음 — 정보 제공만.
"""
import json
import sys
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).parent
DATA = ROOT / 'data_cache'
STATE = ROOT / 'state'
SUBS_CACHE = ROOT / '_phase_c_name_to_ticker.json'

# 9 산업지주사 (확정)
HOLDINGS = [
    ('402340', 'SK스퀘어'),
    ('034730', 'SK'),
    ('009540', 'HD한국조선해양'),
    ('267250', 'HD현대'),
    ('003550', 'LG'),
    ('006260', 'LS'),
    ('180640', '한진칼'),
    ('078930', 'GS'),
    ('001040', 'CJ'),
]

# 디스카운트 임계 (메시지 표시 기준)
DISCOUNT_DISPLAY_THRESHOLD = 0.20  # 20% 이상만 표시 (premium = 음수 디스카운트 표시 X)


def compute_nav_discount(base_date: str) -> dict:
    """base_date 시점 9 지주사 NAV 디스카운트 계산.

    Args:
        base_date: YYYYMMDD

    Returns:
        {
          'base_date': '20260515',
          'holdings': [
            {'ticker': '402340', 'name': 'SK스퀘어', 'mc': 144.89, 'nav': 260.62, 'discount_pct': 44.4, 'subs_count': 23},
            ...
          ]
        }
    """
    # 시가 파일 로드
    mc_file = DATA / f'market_cap_ALL_{base_date}.parquet'
    if not mc_file.exists():
        # 가장 가까운 이전 파일
        files = sorted(DATA.glob('market_cap_ALL_*.parquet'))
        files = [f for f in files if f.stem.replace('market_cap_ALL_', '') <= base_date]
        if not files:
            return {'base_date': base_date, 'holdings': [], 'error': 'no market_cap file'}
        mc_file = files[-1]
    mc = pd.read_parquet(mc_file)
    mc_map = dict(zip(mc.index.astype(str).str.zfill(6), mc['시가총액']))

    # 자회사 매핑 캐시 (분기 1회 갱신, _phase_c_step3_subs.csv가 메인)
    subs_csv = ROOT / '_phase_c_subs.csv'
    if not subs_csv.exists():
        return {'base_date': base_date, 'holdings': [], 'error': 'subs csv missing'}
    subs = pd.read_csv(subs_csv)

    # 수동 ticker 매핑 캐시 (find_corp_code 결과)
    manual = {}
    if SUBS_CACHE.exists():
        manual = json.load(open(SUBS_CACHE, 'r', encoding='utf-8'))

    result = {'base_date': base_date, 'holdings': []}
    for h_tk, h_name in HOLDINGS:
        h_mc = mc_map.get(h_tk, 0)
        chunk = subs[subs['holding'] == h_name] if h_name in subs['holding'].values \
                else subs[subs['holding_ticker'].astype(str).str.zfill(6) == h_tk]
        if chunk.empty or h_mc == 0:
            result['holdings'].append({
                'ticker': h_tk, 'name': h_name, 'mc_won': h_mc, 'nav_won': 0,
                'discount_pct': None, 'subs_count': 0, 'subs_listed': 0,
            })
            continue

        # 자회사별 시가 × 지분율 합산
        nav = 0
        listed_count = 0
        for _, row in chunk.iterrows():
            sub_name = row.get('sub_clean', row.get('sub_name', ''))
            # 매핑: 1) manual (find_corp_code) 2) row.sub_ticker
            sub_tk = manual.get(sub_name) or row.get('sub_ticker') or ''
            sub_tk = str(sub_tk).zfill(6) if sub_tk else ''
            sub_mc = mc_map.get(sub_tk, 0) if sub_tk else 0
            if sub_mc > 0:
                listed_count += 1
                qota = row.get('qota_pct', 0)
                nav += sub_mc * qota / 100

        disc = (1 - h_mc / nav) if nav > 0 else None
        result['holdings'].append({
            'ticker': h_tk,
            'name': h_name,
            'mc_won': h_mc,
            'nav_won': nav,
            'mc_jo': round(h_mc / 1e12, 2),
            'nav_jo': round(nav / 1e12, 2),
            'discount_pct': round(disc * 100, 1) if disc is not None else None,
            'subs_count': len(chunk),
            'subs_listed': listed_count,
        })

    return result


def format_nav_discount_section(nav_data: dict) -> str:
    """텔레그램 메시지용 NAV 디스카운트 섹션 (Watchlist 끝에 추가)."""
    if not nav_data or not nav_data.get('holdings'):
        return ''
    holdings = nav_data['holdings']
    # 디스카운트 20% 이상만 (premium 또는 평가 불가 제외)
    target = [h for h in holdings
              if h.get('discount_pct') is not None and h['discount_pct'] >= DISCOUNT_DISPLAY_THRESHOLD * 100]
    target.sort(key=lambda x: -x['discount_pct'])

    if not target:
        return ''

    lines = [
        '',
        '━━━━━━━━━━━━━━━',
        '📊 산업지주사 NAV 디스카운트',
        '━━━━━━━━━━━━━━━',
        '(매매 신호 X, 별도 참고 정보)',
    ]
    for h in target:
        lines.append(f'• {h["name"]}({h["ticker"]}): 시총 {h["mc_jo"]}조 vs NAV {h["nav_jo"]}조 = <b>{h["discount_pct"]:.1f}%</b> 디스카운트')
    lines.append('')
    lines.append('※ 자회사 시가 × 지분율 합산 기준. 본업 가치 미포함.')
    return '\n'.join(lines)


def save_nav_state(nav_data: dict):
    """state/nav_discount.json 저장"""
    out = STATE / 'nav_discount.json'
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(nav_data, f, ensure_ascii=False, indent=2, default=str)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    base_date = sys.argv[1] if len(sys.argv) > 1 else '20260515'
    data = compute_nav_discount(base_date)
    save_nav_state(data)
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    print('\n=== 텔레그램 형식 ===')
    print(format_nav_discount_section(data))
