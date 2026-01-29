"""
포트폴리오 결과 시각화 및 분석
- 전략 A (마법공식) vs 전략 B (멀티팩터) 비교
- 팩터 분포 및 특성 분석
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib import font_manager
import warnings
warnings.filterwarnings('ignore')

# 한글 폰트 설정
plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False
sns.set_style('whitegrid')

print("=" * 80)
print("포트폴리오 결과 시각화 및 분석")
print("=" * 80)

# ============================================================================
# 1. 데이터 로드
# ============================================================================
print("\n[1단계] 데이터 로드")

# 전략 A: 마법공식 (종목코드를 문자열로 읽기)
df_a = pd.read_csv('strategy_a_portfolio.csv', encoding='utf-8-sig', dtype={'종목코드': str})
# 종목코드 0 패딩
df_a['종목코드'] = df_a['종목코드'].str.zfill(6)
print(f"전략 A 종목 수: {len(df_a)}")
print(df_a.head())

# 전략 B: 멀티팩터 (종목코드를 문자열로 읽기)
df_b = pd.read_csv('strategy_b_portfolio.csv', encoding='utf-8-sig', dtype={'종목코드': str})
# 종목코드 0 패딩
df_b['종목코드'] = df_b['종목코드'].str.zfill(6)
print(f"\n전략 B 종목 수: {len(df_b)}")
print(df_b.head())

# 종목명 매핑 (수동)
ticker_names = {
    '005930': '삼성전자',
    '000660': 'SK하이닉스',
    '051910': 'LG화학',
    '006400': '삼성SDI',
    '035420': 'NAVER',
    '005380': '현대차',
    '035720': '카카오',
    '000270': '기아',
    '068270': '셀트리온',
    '207940': '삼성바이오',
    '005490': 'POSCO홀딩스',
    '105560': 'KB금융',
    '055550': '신한지주',
    '028260': '삼성물산',
    '012330': '현대모비스',
    '066570': 'LG전자',
    '096770': 'SK이노베이션',
    '003550': 'LG',
    '034730': 'SK',
    '017670': 'SK텔레콤',
}

df_a['종목명'] = df_a['종목코드'].map(ticker_names)
df_b['종목명'] = df_b['종목코드'].map(ticker_names)

# ============================================================================
# 2. 전략 A: 마법공식 분석
# ============================================================================
print("\n" + "=" * 80)
print("[2단계] 전략 A: 마법공식 분석")
print("=" * 80)

fig, axes = plt.subplots(2, 2, figsize=(16, 12))

# 2-1. 이익수익률 vs 투하자본수익률 산점도
ax1 = axes[0, 0]
scatter = ax1.scatter(df_a['투하자본수익률'], df_a['이익수익률'],
                     s=200, c=df_a['마법공식_순위'],
                     cmap='RdYlGn_r', alpha=0.7, edgecolors='black', linewidth=1.5)

# 상위 5종목 표시
for idx, row in df_a.head(5).iterrows():
    ax1.annotate(row['종목명'],
                xy=(row['투하자본수익률'], row['이익수익률']),
                xytext=(10, 10), textcoords='offset points',
                fontsize=9, fontweight='bold',
                bbox=dict(boxstyle='round,pad=0.5', fc='yellow', alpha=0.7),
                arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0'))

ax1.set_xlabel('투하자본수익률 (ROC)', fontsize=12, fontweight='bold')
ax1.set_ylabel('이익수익률 (Earnings Yield)', fontsize=12, fontweight='bold')
ax1.set_title('마법공식: 이익수익률 vs 투하자본수익률', fontsize=14, fontweight='bold')
ax1.grid(True, alpha=0.3)
plt.colorbar(scatter, ax=ax1, label='순위 (낮을수록 좋음)')

# 2-2. 마법공식 순위별 팩터 값
ax2 = axes[0, 1]
top10 = df_a.head(10).sort_values('마법공식_순위')
x = np.arange(len(top10))
width = 0.35

bars1 = ax2.bar(x - width/2, top10['이익수익률'] * 100, width,
                label='이익수익률', alpha=0.8, color='steelblue')
bars2 = ax2.bar(x + width/2, top10['투하자본수익률'] * 100, width,
                label='투하자본수익률', alpha=0.8, color='coral')

ax2.set_xlabel('종목', fontsize=12, fontweight='bold')
ax2.set_ylabel('수익률 (%)', fontsize=12, fontweight='bold')
ax2.set_title('마법공식 상위 10종목 팩터 비교', fontsize=14, fontweight='bold')
ax2.set_xticks(x)
ax2.set_xticklabels(top10['종목명'], rotation=45, ha='right')
ax2.legend()
ax2.grid(True, alpha=0.3, axis='y')

# 2-3. 팩터 분포 (박스플롯)
ax3 = axes[1, 0]
factor_data = [df_a['이익수익률'] * 100, df_a['투하자본수익률'] * 100]
bp = ax3.boxplot(factor_data, labels=['이익수익률', '투하자본수익률'],
                 patch_artist=True, notch=True, showmeans=True)

colors = ['lightblue', 'lightcoral']
for patch, color in zip(bp['boxes'], colors):
    patch.set_facecolor(color)
    patch.set_alpha(0.7)

ax3.set_ylabel('수익률 (%)', fontsize=12, fontweight='bold')
ax3.set_title('마법공식 팩터 분포', fontsize=14, fontweight='bold')
ax3.grid(True, alpha=0.3, axis='y')

# 2-4. 순위별 종목명
ax4 = axes[1, 1]
top10_sorted = df_a.head(10).sort_values('마법공식_순위', ascending=False)
y_pos = np.arange(len(top10_sorted))

bars = ax4.barh(y_pos, top10_sorted['마법공식_순위'],
                color='steelblue', alpha=0.7, edgecolor='black')

# 색상 그라데이션
colors = plt.cm.RdYlGn_r(np.linspace(0.3, 0.9, len(top10_sorted)))
for bar, color in zip(bars, colors):
    bar.set_color(color)

ax4.set_yticks(y_pos)
ax4.set_yticklabels(top10_sorted['종목명'])
ax4.invert_xaxis()
ax4.set_xlabel('순위 (낮을수록 좋음)', fontsize=12, fontweight='bold')
ax4.set_title('마법공식 종목별 순위', fontsize=14, fontweight='bold')
ax4.grid(True, alpha=0.3, axis='x')

plt.tight_layout()
plt.savefig('strategy_a_analysis.png', dpi=300, bbox_inches='tight')
print("\n전략 A 시각화 저장: strategy_a_analysis.png")

# ============================================================================
# 3. 전략 B: 멀티팩터 분석
# ============================================================================
print("\n" + "=" * 80)
print("[3단계] 전략 B: 멀티팩터 분석")
print("=" * 80)

fig, axes = plt.subplots(2, 2, figsize=(16, 12))

# 3-1. 밸류 점수 vs 멀티팩터 점수
ax1 = axes[0, 0]
scatter = ax1.scatter(df_b['밸류_점수'], df_b['멀티팩터_점수'],
                     s=200, c=df_b['멀티팩터_순위'],
                     cmap='RdYlGn_r', alpha=0.7, edgecolors='black', linewidth=1.5)

# 상위 5종목 표시
for idx, row in df_b.head(5).iterrows():
    ax1.annotate(row['종목명'],
                xy=(row['밸류_점수'], row['멀티팩터_점수']),
                xytext=(10, 10), textcoords='offset points',
                fontsize=9, fontweight='bold',
                bbox=dict(boxstyle='round,pad=0.5', fc='yellow', alpha=0.7),
                arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0'))

ax1.set_xlabel('밸류 점수', fontsize=12, fontweight='bold')
ax1.set_ylabel('멀티팩터 종합 점수', fontsize=12, fontweight='bold')
ax1.set_title('멀티팩터: 밸류 점수 vs 종합 점수', fontsize=14, fontweight='bold')
ax1.grid(True, alpha=0.3)
plt.colorbar(scatter, ax=ax1, label='순위 (낮을수록 좋음)')

# 3-2. PER vs PBR 산점도
ax2 = axes[0, 1]

# PER이 0인 종목 제외 (적자)
df_b_filtered = df_b[df_b['PER'] > 0].copy()

scatter = ax2.scatter(df_b_filtered['PER'], df_b_filtered['PBR'],
                     s=200, c=df_b_filtered['멀티팩터_순위'],
                     cmap='RdYlGn_r', alpha=0.7, edgecolors='black', linewidth=1.5)

for idx, row in df_b_filtered.head(5).iterrows():
    ax2.annotate(row['종목명'],
                xy=(row['PER'], row['PBR']),
                xytext=(10, 10), textcoords='offset points',
                fontsize=9, fontweight='bold',
                bbox=dict(boxstyle='round,pad=0.5', fc='lightgreen', alpha=0.7),
                arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0'))

ax2.set_xlabel('PER (낮을수록 저평가)', fontsize=12, fontweight='bold')
ax2.set_ylabel('PBR (낮을수록 저평가)', fontsize=12, fontweight='bold')
ax2.set_title('멀티팩터: PER vs PBR', fontsize=14, fontweight='bold')
ax2.grid(True, alpha=0.3)
ax2.set_xlim(left=0)
ax2.set_ylim(bottom=0)
plt.colorbar(scatter, ax=ax2, label='순위')

# 3-3. 상위 10종목 팩터 비교
ax3 = axes[1, 0]
top10 = df_b.head(10).sort_values('멀티팩터_순위')
x = np.arange(len(top10))

bars = ax3.bar(x, top10['멀티팩터_점수'],
               color='steelblue', alpha=0.7, edgecolor='black')

# 색상 그라데이션
colors = plt.cm.RdYlGn(np.linspace(0.3, 0.9, len(top10)))
for bar, color in zip(bars, colors):
    bar.set_color(color)

ax3.set_xlabel('종목', fontsize=12, fontweight='bold')
ax3.set_ylabel('멀티팩터 점수', fontsize=12, fontweight='bold')
ax3.set_title('멀티팩터 상위 10종목 점수', fontsize=14, fontweight='bold')
ax3.set_xticks(x)
ax3.set_xticklabels(top10['종목명'], rotation=45, ha='right')
ax3.grid(True, alpha=0.3, axis='y')

# 3-4. 배당수익률 분석
ax4 = axes[1, 1]
top10_div = df_b.head(10).sort_values('DIV', ascending=False)
y_pos = np.arange(len(top10_div))

bars = ax4.barh(y_pos, top10_div['DIV'],
                color='coral', alpha=0.7, edgecolor='black')

ax4.set_yticks(y_pos)
ax4.set_yticklabels(top10_div['종목명'])
ax4.set_xlabel('배당수익률 (%)', fontsize=12, fontweight='bold')
ax4.set_title('상위 10종목 배당수익률', fontsize=14, fontweight='bold')
ax4.grid(True, alpha=0.3, axis='x')

plt.tight_layout()
plt.savefig('strategy_b_analysis.png', dpi=300, bbox_inches='tight')
print("\n전략 B 시각화 저장: strategy_b_analysis.png")

# ============================================================================
# 4. 전략 비교 분석
# ============================================================================
print("\n" + "=" * 80)
print("[4단계] 전략 A vs B 비교 분석")
print("=" * 80)

fig, axes = plt.subplots(2, 2, figsize=(16, 12))

# 4-1. 겹치는 종목 분석
ax1 = axes[0, 0]
common_tickers = set(df_a['종목코드'].head(10)) & set(df_b['종목코드'].head(10))
a_only = set(df_a['종목코드'].head(10)) - common_tickers
b_only = set(df_b['종목코드'].head(10)) - common_tickers

sizes = [len(common_tickers), len(a_only), len(b_only)]
labels = [f'공통\n({len(common_tickers)}개)',
          f'전략 A만\n({len(a_only)}개)',
          f'전략 B만\n({len(b_only)}개)']
colors = ['#ff9999', '#66b3ff', '#99ff99']
explode = (0.1, 0, 0)

ax1.pie(sizes, explode=explode, labels=labels, colors=colors,
        autopct='%1.1f%%', shadow=True, startangle=90,
        textprops={'fontsize': 12, 'fontweight': 'bold'})
ax1.set_title('전략 간 종목 중복도 (상위 10개)', fontsize=14, fontweight='bold')

# 4-2. 공통 종목 상세
ax2 = axes[0, 1]
if common_tickers:
    common_names = [ticker_names.get(t, t) for t in common_tickers]
    text = "공통 선정 종목:\n\n"
    for i, (ticker, name) in enumerate(zip(common_tickers, common_names), 1):
        text += f"{i}. {name} ({ticker})\n"
    ax2.text(0.1, 0.5, text, fontsize=12, verticalalignment='center',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    ax2.axis('off')
    ax2.set_title('양 전략 공통 선정 종목', fontsize=14, fontweight='bold')
else:
    ax2.text(0.5, 0.5, '공통 종목 없음', fontsize=14, ha='center', va='center')
    ax2.axis('off')

# 4-3. 순위 비교 (공통 종목)
ax3 = axes[1, 0]
if common_tickers:
    comparison_data = []
    for ticker in common_tickers:
        name = ticker_names.get(ticker, ticker)
        rank_a = df_a[df_a['종목코드'] == ticker]['마법공식_순위'].values[0]
        rank_b = df_b[df_b['종목코드'] == ticker]['멀티팩터_순위'].values[0]
        comparison_data.append({'종목명': name, '전략A순위': rank_a, '전략B순위': rank_b})

    comp_df = pd.DataFrame(comparison_data).sort_values('전략A순위')
    x = np.arange(len(comp_df))
    width = 0.35

    ax3.bar(x - width/2, comp_df['전략A순위'], width, label='전략 A (마법공식)',
            alpha=0.8, color='steelblue')
    ax3.bar(x + width/2, comp_df['전략B순위'], width, label='전략 B (멀티팩터)',
            alpha=0.8, color='coral')

    ax3.set_xlabel('종목', fontsize=12, fontweight='bold')
    ax3.set_ylabel('순위 (낮을수록 좋음)', fontsize=12, fontweight='bold')
    ax3.set_title('공통 종목 순위 비교', fontsize=14, fontweight='bold')
    ax3.set_xticks(x)
    ax3.set_xticklabels(comp_df['종목명'], rotation=45, ha='right')
    ax3.legend()
    ax3.invert_yaxis()
    ax3.grid(True, alpha=0.3, axis='y')
else:
    ax3.text(0.5, 0.5, '공통 종목이 없어 비교 불가', fontsize=12, ha='center', va='center')
    ax3.axis('off')

# 4-4. 전략별 특징 요약
ax4 = axes[1, 1]
summary_text = """
전략 비교 요약

【전략 A: 마법공식】
• 이익수익률 (EBIT/EV)
• 투하자본수익률 (EBIT/IC)
• 밸류 + 퀄리티 조합
• 상위 1위: SK하이닉스

【전략 B: 멀티팩터】
• PER, PBR (밸류)
• 배당수익률
• 다각도 평가
• 상위 1위: SK

【특징】
✓ 전략 A: 수익성 중시
✓ 전략 B: 저평가 중시
✓ 공통: 우량 대형주 선호
"""

ax4.text(0.05, 0.95, summary_text, fontsize=11, verticalalignment='top',
         family='monospace',
         bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.5))
ax4.axis('off')

plt.tight_layout()
plt.savefig('strategy_comparison.png', dpi=300, bbox_inches='tight')
print("\n전략 비교 시각화 저장: strategy_comparison.png")

# ============================================================================
# 5. 통계 분석 리포트
# ============================================================================
print("\n" + "=" * 80)
print("[5단계] 통계 분석 리포트")
print("=" * 80)

print("\n【전략 A: 마법공식 통계】")
print(f"평균 이익수익률: {df_a['이익수익률'].mean():.4f} ({df_a['이익수익률'].mean()*100:.2f}%)")
print(f"평균 투하자본수익률: {df_a['투하자본수익률'].mean():.4f} ({df_a['투하자본수익률'].mean()*100:.2f}%)")
print(f"최고 이익수익률: {df_a['이익수익률'].max():.4f} - {df_a.loc[df_a['이익수익률'].idxmax(), '종목명']}")
print(f"최고 투하자본수익률: {df_a['투하자본수익률'].max():.4f} - {df_a.loc[df_a['투하자본수익률'].idxmax(), '종목명']}")

print("\n【전략 B: 멀티팩터 통계】")
df_b_per = df_b[df_b['PER'] > 0]  # 적자 종목 제외
print(f"평균 PER: {df_b_per['PER'].mean():.2f}")
print(f"평균 PBR: {df_b['PBR'].mean():.2f}")
print(f"평균 배당수익률: {df_b['DIV'].mean():.2f}%")
print(f"평균 멀티팩터 점수: {df_b['멀티팩터_점수'].mean():.4f}")
print(f"최저 PER: {df_b_per['PER'].min():.2f} - {df_b_per.loc[df_b_per['PER'].idxmin(), '종목명']}")
print(f"최고 배당수익률: {df_b['DIV'].max():.2f}% - {df_b.loc[df_b['DIV'].idxmax(), '종목명']}")

print("\n【종목 중복 분석】")
print(f"전략 A 상위 10개: {', '.join([str(x) for x in df_a['종목명'].head(10).tolist()])}")
print(f"전략 B 상위 10개: {', '.join([str(x) for x in df_b['종목명'].head(10).tolist()])}")
print(f"공통 종목 수: {len(common_tickers)}개")
if common_tickers:
    common_names_list = [ticker_names.get(t, t) for t in common_tickers]
    print(f"공통 종목: {', '.join(common_names_list)}")

# ============================================================================
# 6. 상세 리포트 저장
# ============================================================================
print("\n" + "=" * 80)
print("[6단계] 상세 리포트 저장")
print("=" * 80)

with open('portfolio_analysis_report.txt', 'w', encoding='utf-8') as f:
    f.write("=" * 80 + "\n")
    f.write("한국 주식 멀티팩터 전략 분석 리포트\n")
    f.write("분석 일자: 2024-12-31 기준\n")
    f.write("=" * 80 + "\n\n")

    f.write("【전략 A: 마법공식】 상위 10종목\n")
    f.write("-" * 80 + "\n")
    for idx, row in df_a.head(10).iterrows():
        f.write(f"{int(row['마법공식_순위']):2d}위. {row['종목명']:12s} ({row['종목코드']}) | ")
        f.write(f"이익수익률: {row['이익수익률']*100:6.2f}% | ")
        f.write(f"투하자본수익률: {row['투하자본수익률']*100:6.2f}%\n")

    f.write("\n【전략 B: 멀티팩터】 상위 10종목\n")
    f.write("-" * 80 + "\n")
    for idx, row in df_b.head(10).iterrows():
        f.write(f"{int(row['멀티팩터_순위']):2d}위. {row['종목명']:12s} ({row['종목코드']}) | ")
        f.write(f"점수: {row['멀티팩터_점수']:.4f} | ")
        f.write(f"PER: {row['PER']:6.2f} | PBR: {row['PBR']:.2f} | DIV: {row['DIV']:.2f}%\n")

    f.write("\n【공통 선정 종목】\n")
    f.write("-" * 80 + "\n")
    if common_tickers:
        for ticker in common_tickers:
            name = ticker_names.get(ticker, ticker)
            rank_a = df_a[df_a['종목코드'] == ticker]['마법공식_순위'].values[0]
            rank_b = df_b[df_b['종목코드'] == ticker]['멀티팩터_순위'].values[0]
            f.write(f"• {name} ({ticker}): 전략A {int(rank_a)}위, 전략B {int(rank_b)}위\n")
    else:
        f.write("공통 종목 없음\n")

    f.write("\n【통계 요약】\n")
    f.write("-" * 80 + "\n")
    f.write(f"전략 A 평균 이익수익률: {df_a['이익수익률'].mean()*100:.2f}%\n")
    f.write(f"전략 A 평균 투하자본수익률: {df_a['투하자본수익률'].mean()*100:.2f}%\n")
    f.write(f"전략 B 평균 PER: {df_b_per['PER'].mean():.2f}\n")
    f.write(f"전략 B 평균 PBR: {df_b['PBR'].mean():.2f}\n")
    f.write(f"전략 B 평균 배당수익률: {df_b['DIV'].mean():.2f}%\n")

print("\n상세 리포트 저장: portfolio_analysis_report.txt")

print("\n" + "=" * 80)
print("시각화 및 분석 완료!")
print("=" * 80)
print("\n생성된 파일:")
print("1. strategy_a_analysis.png        - 전략 A (마법공식) 분석")
print("2. strategy_b_analysis.png        - 전략 B (멀티팩터) 분석")
print("3. strategy_comparison.png        - 전략 비교")
print("4. portfolio_analysis_report.txt  - 상세 텍스트 리포트")

plt.show()
