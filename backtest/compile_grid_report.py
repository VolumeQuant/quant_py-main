"""모든 stage 결과 정리 → 텔레그램 개인봇 발송 (채널 절대 X)"""
import sys, os, json
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd
from pathlib import Path
import requests

PROJECT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT))
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID

STAGES = {
    'stage1_regime_results.csv': '국면 (MA × 확인일수)',
    'stage2_boost_results.csv': 'Boost V/Q/G/M',
    'stage3_def_results.csv': 'Defense V/Q/G/M',
    'stage4a_boost_gsub.csv': 'Boost G_SUB + MOM',
    'stage4b_def_gsub.csv': 'Defense G_SUB + MOM',
    'stage5_entry_results.csv': '진입/이탈/슬롯',
    'stage6_sl_results.csv': '손절/이익실현/쿨다운',
}

def fmt_baseline_section():
    """baseline BT 결과 (bt_with_new_ohlcv.py log)"""
    log_fp = PROJECT / 'logs' / 'grid_baseline.log'
    if not log_fp.exists(): return '⚠️ baseline 측정 없음'
    text = log_fp.read_text(encoding='utf-8', errors='replace')
    # Cal/CAGR/MDD 추출
    lines = [l for l in text.split('\n') if any(k in l for k in ['Cal','CAGR','MDD','Sharpe','Sortino','Total','Avg'])]
    return '\n'.join(lines[-7:])


def fmt_stage_top(csv_name, label, top_n=3):
    fp = PROJECT / 'backtest' / csv_name
    if not fp.exists():
        return f'\n📊 {label}\n  ⚠️ 결과 파일 없음'
    df = pd.read_csv(fp)
    if 'calmar' not in df.columns:
        return f'\n📊 {label}\n  ⚠️ calmar 컬럼 없음'
    df = df.sort_values('calmar', ascending=False).head(top_n)
    out = [f'\n📊 {label}']
    for _, r in df.iterrows():
        params = []
        for c in df.columns:
            if c in ['cagr','sharpe','sortino','calmar','mdd','total','b_cagr','alpha','avg_holdings','_daily_rets','is_baseline','elapsed','kind']:
                continue
            v = r[c]
            if isinstance(v, float):
                params.append(f'{c}={v:.2f}')
            else:
                params.append(f'{c}={v}')
        param_str = ' '.join(params)
        out.append(f'  Cal {r["calmar"]:.2f} | CAGR {r["cagr"]:.0f}% | MDD {r["mdd"]:.0f}% | {param_str}')
    return '\n'.join(out)


def main():
    msg_parts = []

    # 헤더
    msg_parts.append('🤖 그리드서치 결과 (v80 7가지 손잡이 검증)\n')
    msg_parts.append('🎯 진행 시기: 2026-05-13 (회사PC 자율 진행)\n')
    msg_parts.append('📅 BT 기간: 2018-07~2026-05 (8년)\n')
    msg_parts.append('🛡️ 안전망: 이격도20 1.5 적용 (production 일치)\n')

    # baseline
    msg_parts.append('\n' + '='*30)
    msg_parts.append('\n📌 현재 baseline (변경 없이)')
    msg_parts.append(f'\n{fmt_baseline_section()}')

    # 각 stage Top 3
    msg_parts.append('\n\n' + '='*30)
    msg_parts.append('\n🏆 각 손잡이별 Top 3 조합')
    for csv, label in STAGES.items():
        msg_parts.append(fmt_stage_top(csv, label, top_n=3))

    msg = ''.join(msg_parts)

    # 길면 분할 (텔레그램 4096자 제한)
    chunks = []
    while len(msg) > 4000:
        cut = msg[:4000].rfind('\n')
        chunks.append(msg[:cut])
        msg = msg[cut:]
    chunks.append(msg)

    for i, c in enumerate(chunks, 1):
        prefix = f'[{i}/{len(chunks)}] ' if len(chunks) > 1 else ''
        try:
            r = requests.post(
                f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage',
                data={'chat_id': TELEGRAM_PRIVATE_ID, 'text': prefix + c},
                timeout=30
            )
            print(f'  msg {i}/{len(chunks)}: {r.status_code}')
        except Exception as e:
            print(f'  msg {i}/{len(chunks)} ERR: {e}')

    print('\n전체 보고서 (콘솔 미리보기):')
    print(''.join(msg_parts)[:2000])


if __name__ == '__main__':
    main()
