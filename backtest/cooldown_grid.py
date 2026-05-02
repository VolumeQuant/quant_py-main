"""쿨다운 그리드서치 — 손절/트레일링 후 재진입 금지 기간 테스트
TurboSim 내부 로직을 재현하되 cooldown 추가
"""
import sys, os, json
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd, numpy as np
import requests
from turbo_simulator import TurboSimulator, _calc_metrics
from pathlib import Path

PROJECT = Path(__file__).parent.parent
from config import TELEGRAM_BOT_TOKEN as BOT, TELEGRAM_PRIVATE_ID as PID
def send_tg(msg):
    if len(msg) > 4096: msg = msg[:4090] + '...'
    requests.post(f'https://api.telegram.org/bot{BOT}/sendMessage',
                  data={'chat_id': PID, 'text': msg, 'parse_mode': 'HTML'}, timeout=30)

def load_rankings(dirs):
    data = {}
    for d in dirs:
        d = Path(d)
        if not d.exists(): continue
        for fp in sorted(d.glob('ranking_*.json')):
            k = fp.stem.replace('ranking_', '')
            if len(k) != 8: continue
            if k not in data:
                with open(fp, 'r', encoding='utf-8') as f: data[k] = json.load(f)
    return data

print('load...', flush=True)
boost = load_rankings([PROJECT/'backtest'/'bt_extended', PROJECT/'state'])
defense = load_rankings([PROJECT/'backtest'/'bt_extended_defense', PROJECT/'state'/'defense'])
dates = sorted(set(boost) & set(defense))
rk = {d: boost[d]['rankings'] for d in dates}
ohlcv = pd.read_parquet(sorted((PROJECT/'data_cache').glob('all_ohlcv_2017*.parquet'))[-1]).replace(0, np.nan)
kospi_df = pd.read_parquet(PROJECT/'data_cache'/'kospi_yf.parquet')
kospi = kospi_df.iloc[:,0].fillna(kospi_df['kospi']).dropna()
ma170 = kospi.rolling(170).mean()

def calc_regime(target_dates):
    reg = {}; md = False; stk = 0; ss = None
    for d in target_dates:
        ts = pd.Timestamp(d); kv = kospi.get(ts); mv = ma170.get(ts)
        if kv is None or pd.isna(mv): reg[d] = md; continue
        s = kv > mv
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= 8 and md != s: md = s
        reg[d] = md
    return reg

GS = ('rev_z','oca_z',None,None,None,None)
V80_O = {'v':0.15,'q':0.00,'g':0.55,'m':0.30,'g_rev':0.6,'entry':3,'exit':6,'slots':3,'mom':'12m'}
V80_D = {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,'entry':3,'exit':6,'slots':5,'mom':'6m-1m'}

PERIODS = {
    '7.8y': ('20180702','20260414'),
    'WF1': ('20180702','20191231'),
    'WF2': ('20200102','20211230'),
    'WF3': ('20220103','20231228'),
    'WF4': ('20240102','20260414'),
}

def run_with_cooldown(pd_, reg, sl_cd, ts_cd, stop_loss=-0.10, trailing=-0.15):
    """TurboSim + cooldown wrapper"""
    # 먼저 TurboSim으로 캐시 빌드
    tsim = TurboSimulator({d: rk[d] for d in pd_}, pd_, ohlcv)
    tsim._ensure_cache(0.15, 0.00, 0.55, 0.30, 0.6, 20, '12m', 'rev_z', 'oca_z')
    boost_flat = list(tsim._cached_flat)
    tsim._ensure_cache(0.30, 0.15, 0.15, 0.40, 0.7, 20, '6m-1m', 'rev_z', 'oca_z')
    defense_flat = list(tsim._cached_flat)

    price_arr = tsim._price_arr
    date_rows = tsim._date_row_indices
    n_dates = len(pd_)

    portfolio = {}  # col -> entry_price
    peak_prices = {}
    cooldown = {}  # col -> remaining_days
    daily_rets = [0.0] * n_dates
    holdings_count = [0] * n_dates
    prev_regime = None

    for i in range(2, n_dates):
        d = pd_[i]
        cr = reg.get(d, False)

        # 국면 전환 → 청산 (쿨다운 없음)
        if prev_regime is not None and cr != prev_regime:
            portfolio.clear()
            peak_prices.clear()
            cooldown.clear()  # 국면 전환 시 쿨다운도 리셋
        prev_regime = cr

        if cr:
            pipe = boost_flat[i] if i < len(boost_flat) else None
            entry_p, exit_p, max_slots = 3, 6, 3
        else:
            pipe = defense_flat[i] if i < len(defense_flat) else None
            entry_p, exit_p, max_slots = 3, 6, 5

        if pipe is None:
            holdings_count[i] = len(portfolio)
            continue

        wrank_arr, cand_cols, cand_prices, cand_wranks = pipe
        cur_row = date_rows[i]
        if cur_row < 0:
            continue

        # 쿨다운 감소
        expired = []
        for col in cooldown:
            cooldown[col] -= 1
            if cooldown[col] <= 0:
                expired.append(col)
        for col in expired:
            del cooldown[col]

        # peak 업데이트
        for col in portfolio:
            cur_p = price_arr[cur_row, col]
            if cur_p == cur_p and cur_p > 0:
                if col in peak_prices:
                    if cur_p > peak_prices[col]:
                        peak_prices[col] = cur_p
                else:
                    peak_prices[col] = cur_p

        # EXIT
        to_remove = []
        for col, ep in portfolio.items():
            cur_p = price_arr[cur_row, col]
            if cur_p != cur_p or cur_p <= 0:
                continue
            reason = None
            if stop_loss is not None and ep > 0:
                if (cur_p / ep - 1.0) <= stop_loss:
                    reason = 'sl'
            if reason is None and trailing is not None:
                pk = peak_prices.get(col, ep)
                if pk > 0 and (cur_p / pk - 1.0) <= trailing:
                    reason = 'ts'
            if reason is None and wrank_arr[col] > exit_p:
                reason = 'rank'

            if reason:
                to_remove.append((col, reason))

        for col, reason in to_remove:
            del portfolio[col]
            if col in peak_prices:
                del peak_prices[col]
            # 쿨다운 적용
            if reason == 'sl' and sl_cd > 0:
                cooldown[col] = sl_cd
            elif reason == 'ts' and ts_cd > 0:
                cooldown[col] = ts_cd

        # ENTRY (쿨다운 체크)
        slots_avail = max_slots - len(portfolio)
        if slots_avail > 0:
            for k in range(len(cand_cols)):
                if slots_avail <= 0:
                    break
                if cand_wranks[k] <= entry_p:
                    c = cand_cols[k]
                    if c not in portfolio and c not in cooldown:
                        portfolio[c] = cand_prices[k]
                        peak_prices[c] = cand_prices[k]
                        slots_avail -= 1

        n_hold = len(portfolio)
        holdings_count[i] = n_hold

        # DAILY RETURN
        if i + 1 < n_dates and n_hold > 0:
            next_row = date_rows[i + 1]
            if next_row >= 0 and cur_row >= 0:
                total_ret = 0.0
                count = 0
                for col in portfolio:
                    c_p = price_arr[next_row, col]
                    p_p = price_arr[cur_row, col]
                    if c_p == c_p and p_p == p_p and p_p > 0:
                        total_ret += c_p / p_p - 1.0
                        count += 1
                daily_rets[i] = total_ret / count if count > 0 else 0.0

    return _calc_metrics(daily_rets, [0.0]*n_dates, holdings_count)

# === 그리드서치 ===
# SL 쿨다운: 0, 1, 2, 3, 5, 7, 10, 15, 20일
# TS 쿨다운: 0, 1, 2, 3, 5, 7, 10, 15, 20일
sl_cds = [0, 1, 2, 3, 5, 7, 10, 15, 20]
ts_cds = [0, 1, 2, 3, 5, 7, 10, 15, 20]

all_results = []
total = len(sl_cds) * len(ts_cds)
count = 0

for sl_cd in sl_cds:
    for ts_cd in ts_cds:
        count += 1
        row = {'sl_cd': sl_cd, 'ts_cd': ts_cd}

        for pname, (ps, pe) in PERIODS.items():
            pd_ = [d for d in dates if ps <= d <= pe]
            if len(pd_) < 20:
                continue
            reg = calc_regime(pd_)
            r = run_with_cooldown(pd_, reg, sl_cd, ts_cd)
            row[pname] = r['calmar']
            if pname == '7.8y':
                row['cagr'] = r['cagr']
                row['mdd'] = r['mdd']

        wf = [row.get(f'WF{i}', 0) for i in range(1, 5)]
        row['wf_min'] = min(wf)
        row['wf_mean'] = np.mean(wf)
        row['cv'] = np.std(wf)/np.mean(wf) if np.mean(wf) > 0 else 99
        all_results.append(row)

        if count % 9 == 0:
            print(f'  [{count}/{total}] SL_cd={sl_cd} TS_cd={ts_cd}: Cal={row.get("7.8y",0):.2f}', flush=True)

# 정렬
rdf = pd.DataFrame(all_results).sort_values('7.8y', ascending=False)
bl = next(r for r in all_results if r['sl_cd'] == 0 and r['ts_cd'] == 0)
bl_cal = bl['7.8y']

# 출력
print(f'\n{"="*90}')
print(f'쿨다운 그리드서치 결과 ({total}조합)')
print(f'{"="*90}')
print(f'baseline (쿨다운 없음): Cal={bl_cal:.2f} CAGR={bl["cagr"]:.1f}% MDD={bl["mdd"]:.1f}%')

print(f'\nTop 15:')
print(f'{"#":>3} {"SL_cd":>6} {"TS_cd":>6} {"Cal":>6} {"CAGR":>7} {"MDD":>6} {"WF1":>5} {"WF2":>5} {"WF3":>5} {"WF4":>5} {"CV":>5} {"d":>6}')
print('-'*80)
for i, (_, r) in enumerate(rdf.head(15).iterrows()):
    d = r['7.8y'] - bl_cal
    wf = [r.get(f'WF{j}',0) for j in range(1,5)]
    cv_ok = r['cv'] < 0.40
    m = ' ***' if d > 0.3 and cv_ok else (' **' if d > 0.1 and cv_ok else (' *' if d > 0 else ''))
    print(f'{i+1:>3} {r["sl_cd"]:>5}d {r["ts_cd"]:>5}d {r["7.8y"]:>6.2f} {r["cagr"]:>7.1f} {r["mdd"]:>6.1f} {wf[0]:>5.2f} {wf[1]:>5.2f} {wf[2]:>5.2f} {wf[3]:>5.2f} {r["cv"]:>5.2f} {d:>+6.2f}{m}')

# 히트맵
print(f'\n=== Calmar 히트맵 (SL쿨다운 x TS쿨다운) ===')
header = f'{"SL/TS":>7}'
for tc in ts_cds:
    header += f' {tc:>5}d'
print(header)
for sc in sl_cds:
    line = f'{sc:>6}d'
    for tc in ts_cds:
        match = next((r for r in all_results if r['sl_cd']==sc and r['ts_cd']==tc), None)
        if match:
            line += f' {match["7.8y"]:>6.2f}'
        else:
            line += f'     -'
    print(line)

# CSV
rdf.to_csv(str(PROJECT/'backtest'/'cooldown_grid_results.csv'), index=False, encoding='utf-8-sig')

# 텔레그램
msg = '<b>[쿨다운 그리드서치 결과]</b>\n\n'
msg += '<b>쿨다운이란?</b>\n'
msg += '손절/트레일링으로 판 종목을 며칠간 다시 안 사는 것\n'
msg += '예: SL쿨다운 5일 = 손절 후 5거래일간 같은 종목 재매수 금지\n\n'
msg += f'현행 (쿨다운 없음): Cal={bl_cal:.2f}\n'
msg += f'테스트: {total}조합\n\n'
msg += '<b>Top 10:</b>\n'
for i, (_, r) in enumerate(rdf.head(10).iterrows()):
    d = r['7.8y'] - bl_cal
    cv_ok = r['cv'] < 0.40
    emoji = '\u2b50' if d > 0.2 and cv_ok else ('\u2705' if d > 0 else '\u274c')
    msg += f'{emoji} SL쿨={r["sl_cd"]:.0f}d TS쿨={r["ts_cd"]:.0f}d\n'
    msg += f'   Cal={r["7.8y"]:.2f}(d{d:+.2f}) CAGR={r["cagr"]:.0f}% CV={r["cv"]:.2f}\n'

best = rdf.iloc[0]
d_best = best['7.8y'] - bl_cal
msg += f'\n<b>결론:</b>\n'
msg += f'최고: SL쿨={best["sl_cd"]:.0f}d TS쿨={best["ts_cd"]:.0f}d Cal={best["7.8y"]:.2f}(d{d_best:+.2f})\n'
if d_best >= 0.3:
    msg += '유의미한 개선!'
elif d_best >= 0.1:
    msg += '소폭 개선'
else:
    msg += '쿨다운 효과 미미'

send_tg(msg)
print('\ntelegram sent')
