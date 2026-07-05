# -*- coding: utf-8 -*-
"""EDA M3 — 거래 MFE/MAE 해부: 보유 중 최대이익(MFE)·최대손실(MAE) 경로.
질문: 승자도 보유 중 얼마나 빠졌었나(버티기 근거) / 패자는 초반에 티가 났나."""
import sys, io, os, glob, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd

R = 'C:/dev/claude-code/quant_py-main'
tr = pd.read_csv(R + '/research/trades_full_2018_2026.csv')
px = pd.read_parquet(R + '/data_cache/all_ohlcv_adj_20170601_20260629.parquet').replace(0, np.nan)

rows = []
for _, x in tr.iterrows():
    t = str(x['t']).zfill(6)
    if t not in px.columns: continue
    ed = pd.Timestamp(str(x['ed'])); xd = pd.Timestamp(str(x['xd']))
    ser = px[t].loc[ed:xd].dropna()
    if len(ser) < 2: continue
    base = ser.iloc[0]
    path = ser / base - 1
    mfe = path.max(); mae = path.min()
    # 첫 3일 경로
    p3 = path.iloc[:min(4, len(path))].iloc[-1]
    rows.append({'name': x['name'], 'ed': x['ed'], 'ret': x['ret'], 'mfe': mfe, 'mae': mae,
                 'p3': p3, 'hold': x['hold_d']})
df = pd.DataFrame(rows)
win = df[df['ret'] > 0]; lose = df[df['ret'] <= 0]
print(f"거래 {len(df)}건 (승 {len(win)} / 패 {len(lose)})")

print("\n===== ① 승자도 보유 중 빠졌었나 (승자의 MAE 분포) =====")
print(f"  승자 평균 MAE: {win['mae'].mean()*100:.1f}% / 중앙 {win['mae'].median()*100:.1f}%")
for thr in [-0.03, -0.05, -0.08, -0.10]:
    pct = (win['mae'] <= thr).mean()*100
    print(f"  보유 중 {thr*100:.0f}% 이상 빠졌던 승자 비율: {pct:.0f}%")
big = win[win['ret'] > 0.5]
print(f"  ★+50% 이상 대박 {len(big)}건의 평균 MAE: {big['mae'].mean()*100:.1f}% (최악 {big['mae'].min()*100:.1f}%)")

print("\n===== ② 패자는 초반(3일)에 티가 났나 =====")
print(f"  첫 3일 수익 — 승자 평균 {win['p3'].mean()*100:+.1f}% / 패자 평균 {lose['p3'].mean()*100:+.1f}%")
# 첫 3일 마이너스였던 거래의 최종 결과
early_neg = df[df['p3'] < 0]; early_pos = df[df['p3'] >= 0]
print(f"  첫 3일 마이너스({len(early_neg)}건) → 최종 승률 {(early_neg['ret']>0).mean()*100:.0f}% / 평균 {early_neg['ret'].mean()*100:+.1f}%")
print(f"  첫 3일 플러스({len(early_pos)}건) → 최종 승률 {(early_pos['ret']>0).mean()*100:.0f}% / 평균 {early_pos['ret'].mean()*100:+.1f}%")
neg5 = df[df['p3'] < -0.05]
print(f"  첫 3일 -5% 이상 급락({len(neg5)}건) → 최종 승률 {(neg5['ret']>0).mean()*100:.0f}% / 평균 {neg5['ret'].mean()*100:+.1f}%")

print("\n===== ③ 놓친 이익 (MFE 대비 실현) =====")
df['capture'] = np.where(df['mfe'] > 0.01, df['ret'] / df['mfe'], np.nan)
print(f"  고점 대비 실현 비율(capture) 중앙값: {df['capture'].median()*100:.0f}%")
mfe_big = df[df['mfe'] > 0.20]
print(f"  보유 중 +20% 이상 찍은 거래 {len(mfe_big)}건 → 최종 평균 {mfe_big['ret'].mean()*100:+.1f}% (고점 평균 {mfe_big['mfe'].mean()*100:+.1f}%)")
giveback = mfe_big[mfe_big['ret'] < mfe_big['mfe'] * 0.5]
print(f"  그중 고점의 절반도 못 지킨 거래: {len(giveback)}건 ({len(giveback)/len(mfe_big)*100:.0f}%)")
