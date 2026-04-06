"""멀티팩터 전 항목 엣지케이스 전수검사"""
import sys, json, pandas as pd, numpy as np
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent.parent))

CACHE = Path(__file__).parent.parent / 'data_cache'
STATE = Path(__file__).parent.parent / 'state'

# 데이터 로드
r = json.load(open(STATE / 'ranking_20260403.json', 'r', encoding='utf-8'))
rankings = r['rankings']
tickers = {x['ticker'] for x in rankings}
rk_map = {x['ticker']: x for x in rankings}

fund = pd.read_parquet(sorted(CACHE.glob('fundamental_batch_ALL_*.parquet'))[-1])
ohlcv = pd.read_parquet(sorted(CACHE.glob('all_ohlcv_*full*.parquet'))[-1]).replace(0, np.nan)

dart_data = {}
for tk in tickers:
    f = CACHE / f'fs_dart_{tk}.parquet'
    if f.exists():
        dart_data[tk] = pd.read_parquet(f)

print(f'ranking {len(rankings)}종목, DART {len(dart_data)}종목')
issues = []

def flag(category, ticker, name, rank, detail):
    issues.append({'cat': category, 'ticker': ticker, 'name': name, 'rank': rank, 'detail': detail})

# ============================================================
print('\n' + '=' * 60)
print('1. VALUE: PER, PBR, PCR, PSR')
print('=' * 60)

for x in rankings:
    tk = x['ticker']
    if tk not in fund.index:
        flag('V-NO_FUND', tk, x['name'], x['composite_rank'], 'pykrx fundamental 없음')
        continue
    row = fund.loc[tk]
    per, pbr, eps, bps = row.get('PER',0), row.get('PBR',0), row.get('EPS',0), row.get('BPS',0)

    if per == 0 and pbr == 0 and eps == 0 and bps == 0:
        flag('V-ALL_ZERO', tk, x['name'], x['composite_rank'], 'PER/PBR/EPS/BPS 전부 0 (적자 or 데이터없음)')
    elif per == 0 and eps == 0:
        flag('V-PER_ZERO', tk, x['name'], x['composite_rank'], f'PER=0 EPS=0 (PBR={pbr:.1f})')
    if pbr < 0:
        flag('V-PBR_NEG', tk, x['name'], x['composite_rank'], f'PBR={pbr:.2f} (자본잠식)')

    # PCR: 시가총액/영업현금흐름
    if tk in dart_data:
        df = dart_data[tk]
        cfo_rows = df[df['계정'] == '영업활동으로인한현금흐름'].sort_values('기준일')
        if not cfo_rows.empty:
            cfo_val = cfo_rows.iloc[-1]['값']
            if cfo_val == 0:
                flag('V-CFO_ZERO', tk, x['name'], x['composite_rank'], 'CFO=0 -> PCR 무한대')
            elif cfo_val < 0:
                flag('V-CFO_NEG', tk, x['name'], x['composite_rank'], f'CFO={cfo_val:,.0f} -> PCR 음수')

        # PSR: 시가총액/매출액
        rev_rows = df[(df['계정'] == '매출액')].sort_values('기준일')
        if not rev_rows.empty:
            rev_val = rev_rows.iloc[-1]['값']
            if rev_val <= 0:
                flag('V-REV_ZERO', tk, x['name'], x['composite_rank'], f'매출액={rev_val:,.0f} -> PSR 계산불가')
        else:
            flag('V-NO_REV', tk, x['name'], x['composite_rank'], 'DART 매출액 없음')

# ============================================================
print('\n' + '=' * 60)
print('2. QUALITY: ROE, GPA, CFO/자산')
print('=' * 60)

for x in rankings:
    tk = x['ticker']
    if tk in fund.index:
        eps, bps = fund.loc[tk].get('EPS', 0), fund.loc[tk].get('BPS', 0)
        if bps == 0:
            flag('Q-ROE_NAN', tk, x['name'], x['composite_rank'], f'BPS=0 -> ROE=NaN (필터 우회!)')
        elif bps > 0 and eps < 0:
            roe = eps / bps * 100
            flag('Q-ROE_NEG', tk, x['name'], x['composite_rank'], f'ROE={roe:.1f}% (적자, 필터 대상)')

    if tk in dart_data:
        df = dart_data[tk]
        # GPA = 매출총이익/자산
        gp = df[df['계정'] == '매출총이익'].sort_values('기준일')
        assets = df[df['계정'] == '자산'].sort_values('기준일')
        if not gp.empty and not assets.empty:
            if assets.iloc[-1]['값'] <= 0:
                flag('Q-ASSET_ZERO', tk, x['name'], x['composite_rank'], f'자산={assets.iloc[-1]["값"]:,.0f}')
            if gp.iloc[-1]['값'] < 0:
                flag('Q-GP_NEG', tk, x['name'], x['composite_rank'], f'매출총이익={gp.iloc[-1]["값"]:,.0f}')
        elif gp.empty:
            # 매출총이익이 없는 종목 (금융업 등)
            has_rev = not df[df['계정'] == '매출액'].empty
            if has_rev:
                flag('Q-NO_GP', tk, x['name'], x['composite_rank'], '매출총이익 없음 (매출액은 있음)')

# ============================================================
print('\n' + '=' * 60)
print('3. GROWTH: 매출성장률, 영업이익변화, 이익률변화')
print('=' * 60)

for x in rankings:
    tk = x['ticker']
    if tk not in dart_data:
        flag('G-NO_DART', tk, x['name'], x['composite_rank'], 'DART 재무 없음')
        continue
    df = dart_data[tk]

    # 영업이익 적자->흑자 턴어라운드 (oca_z 폭등 원인)
    oi = df[(df['계정'] == '영업이익') & (df['공시구분'] == 'y')].sort_values('기준일')
    if len(oi) >= 2:
        prev, curr = oi.iloc[-2]['값'], oi.iloc[-1]['값']
        if prev < 0 and curr > 0:
            oca_z = x.get('oca_z', 0)
            flag('G-TURNAROUND', tk, x['name'], x['composite_rank'],
                 f'영업이익 {prev:,.0f}->{curr:,.0f} oca_z={oca_z:.2f}')
        if prev == 0 and curr != 0:
            flag('G-OI_FROM_ZERO', tk, x['name'], x['composite_rank'],
                 f'영업이익 0->{curr:,.0f} (0으로 나누기)')

    # 당기순이익 적자 (pykrx에서 안 잡히는 적자)
    ni = df[(df['계정'] == '당기순이익') & (df['공시구분'] == 'y')].sort_values('기준일')
    if not ni.empty and ni.iloc[-1]['값'] < 0:
        # pykrx에서 EPS=0으로 나오는지
        if tk in fund.index and fund.loc[tk].get('EPS', 0) == 0:
            flag('G-HIDDEN_LOSS', tk, x['name'], x['composite_rank'],
                 f'DART 순이익={ni.iloc[-1]["값"]:,.0f} but pykrx EPS=0')

    # 매출액 0 or 매우 작은 경우 (성장률 계산 왜곡)
    rev = df[(df['계정'] == '매출액') & (df['공시구분'] == 'y')].sort_values('기준일')
    if len(rev) >= 2:
        prev_rev, curr_rev = rev.iloc[-2]['값'], rev.iloc[-1]['값']
        if prev_rev > 0 and prev_rev < 10:  # 매출 10억 미만
            yoy = (curr_rev / prev_rev - 1) * 100
            if abs(yoy) > 500:
                flag('G-REV_EXTREME', tk, x['name'], x['composite_rank'],
                     f'매출 {prev_rev:,.0f}->{curr_rev:,.0f} YoY={yoy:,.0f}%')

# ============================================================
print('\n' + '=' * 60)
print('4. MOMENTUM')
print('=' * 60)

for x in rankings:
    tk = x['ticker']
    if tk in ohlcv.columns:
        prices = ohlcv[tk].dropna()
        days = len(prices)
        if days < 252:
            first = prices.index[0].strftime('%Y-%m-%d')
            flag('M-SHORT_HIST', tk, x['name'], x['composite_rank'], f'{days}일 ({first}~) 1년미만')
        if days < 126:
            flag('M-VERY_SHORT', tk, x['name'], x['composite_rank'], f'{days}일 6개월미만')
    else:
        flag('M-NO_OHLCV', tk, x['name'], x['composite_rank'], 'OHLCV 없음')

# ============================================================
print('\n' + '=' * 60)
print('5. 복합 위험 (여러 팩터 동시 이상)')
print('=' * 60)

# 종목별 이슈 카운트
from collections import Counter
ticker_issues = Counter()
for iss in issues:
    ticker_issues[iss['ticker']] += 1

multi_issue = [(tk, cnt) for tk, cnt in ticker_issues.items() if cnt >= 3]
multi_issue.sort(key=lambda x: -x[1])
print(f'\n3개 이상 이슈: {len(multi_issue)}종목')
for tk, cnt in multi_issue[:15]:
    x = rk_map[tk]
    my_issues = [i for i in issues if i['ticker'] == tk]
    print(f'  {x["composite_rank"]:>3}위 {tk} {x["name"]} ({cnt}개 이슈)')
    for i in my_issues:
        print(f'       [{i["cat"]}] {i["detail"]}')

# ============================================================
print('\n' + '=' * 60)
print('요약')
print('=' * 60)

cat_counts = Counter(i['cat'] for i in issues)
for cat, cnt in cat_counts.most_common():
    print(f'  {cat}: {cnt}종목')
print(f'\n총 이슈: {len(issues)}건, {len(ticker_issues)}종목')

# 상위 20위 내 이슈
top20_issues = [i for i in issues if i['rank'] <= 20]
if top20_issues:
    print(f'\n*** Top 20 내 이슈: {len(top20_issues)}건 ***')
    for i in sorted(top20_issues, key=lambda x: x['rank']):
        print(f'  {i["rank"]:>3}위 {i["ticker"]} {i["name"]} [{i["cat"]}] {i["detail"]}')
