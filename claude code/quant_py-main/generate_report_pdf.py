"""
퀀트 투자 전략 포트폴리오 보고서 PDF 생성
2026년 1분기 포트폴리오 (2025년 3분기 재무제표 기준)
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib import rcParams
from pathlib import Path
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# 한글 폰트 설정
plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False

# PDF 생성을 위한 라이브러리
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak, KeepTogether
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# 한글 폰트 등록
try:
    pdfmetrics.registerFont(TTFont('MalgunGothic', 'C:/Windows/Fonts/malgun.ttf'))
    pdfmetrics.registerFont(TTFont('MalgunGothicBold', 'C:/Windows/Fonts/malgunbd.ttf'))
    FONT_NAME = 'MalgunGothic'
    FONT_BOLD = 'MalgunGothicBold'
except Exception:
    FONT_NAME = 'Helvetica'
    FONT_BOLD = 'Helvetica-Bold'

# 경로 설정
BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / 'output'
OUTPUT_DIR.mkdir(exist_ok=True)

# 색상 정의
COLORS = {
    'primary': colors.HexColor('#1e3a5f'),      # 진한 파랑
    'secondary': colors.HexColor('#3d7ea6'),    # 중간 파랑
    'accent': colors.HexColor('#f39c12'),       # 골드
    'success': colors.HexColor('#27ae60'),      # 녹색
    'danger': colors.HexColor('#e74c3c'),       # 빨강
    'light': colors.HexColor('#ecf0f1'),        # 밝은 회색
    'dark': colors.HexColor('#2c3e50'),         # 진한 회색
}


def create_charts():
    """차트 이미지 생성"""
    charts = {}

    # 1. 전략 A 섹터 분포 차트
    fig, ax = plt.subplots(figsize=(8, 5))
    sectors_a = ['화장품/미용', '엔터테인먼트', '제약/헬스케어', 'IT/소프트웨어', '제조업', '기타']
    values_a = [3, 2, 3, 4, 5, 3]
    colors_a = ['#e74c3c', '#9b59b6', '#3498db', '#2ecc71', '#f39c12', '#95a5a6']

    wedges, texts, autotexts = ax.pie(values_a, labels=sectors_a, autopct='%1.0f%%',
                                       colors=colors_a, startangle=90,
                                       textprops={'fontsize': 11, 'fontweight': 'bold'})
    ax.set_title('전략 A (마법공식) 섹터 분포', fontsize=14, fontweight='bold', pad=20)
    plt.tight_layout()
    chart_path_a = OUTPUT_DIR / 'chart_strategy_a_sector.png'
    plt.savefig(chart_path_a, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()
    charts['sector_a'] = str(chart_path_a)

    # 2. 전략 B 섹터 분포 차트
    fig, ax = plt.subplots(figsize=(8, 5))
    sectors_b = ['K-뷰티/화장품', '게임', '플랫폼/IT', '반도체', '서비스', '기타']
    values_b = [4, 3, 5, 2, 4, 2]
    colors_b = ['#e74c3c', '#9b59b6', '#3498db', '#2ecc71', '#f39c12', '#95a5a6']

    wedges, texts, autotexts = ax.pie(values_b, labels=sectors_b, autopct='%1.0f%%',
                                       colors=colors_b, startangle=90,
                                       textprops={'fontsize': 11, 'fontweight': 'bold'})
    ax.set_title('전략 B (멀티팩터) 섹터 분포', fontsize=14, fontweight='bold', pad=20)
    plt.tight_layout()
    chart_path_b = OUTPUT_DIR / 'chart_strategy_b_sector.png'
    plt.savefig(chart_path_b, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()
    charts['sector_b'] = str(chart_path_b)

    # 3. 전략 A TOP 10 이익수익률 바 차트
    fig, ax = plt.subplots(figsize=(10, 6))
    stocks_a = ['브이티', '제닉', '티앤엘', '휴메딕스', 'F&F', '제룡전기', 'SOOP', 'JYP Ent.', 'SK스퀘어', '크래프톤']
    ey_values = [15.6, 13.0, 13.8, 15.4, 14.8, 10.7, 11.5, 8.8, 10.3, 12.5]
    roc_values = [44.9, 54.0, 29.9, 26.5, 25.6, 33.3, 27.8, 38.2, 28.1, 21.3]

    x = np.arange(len(stocks_a))
    width = 0.35

    bars1 = ax.bar(x - width/2, ey_values, width, label='이익수익률 (%)', color='#3498db')
    bars2 = ax.bar(x + width/2, roc_values, width, label='투하자본수익률 (%)', color='#e74c3c')

    ax.set_ylabel('비율 (%)', fontsize=12)
    ax.set_title('전략 A TOP 10 종목 - 핵심 지표', fontsize=14, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(stocks_a, rotation=45, ha='right', fontsize=10)
    ax.legend(loc='upper right')
    ax.set_ylim(0, 60)

    for bar in bars1:
        height = bar.get_height()
        ax.annotate(f'{height:.1f}', xy=(bar.get_x() + bar.get_width()/2, height),
                   xytext=(0, 3), textcoords="offset points", ha='center', va='bottom', fontsize=8)
    for bar in bars2:
        height = bar.get_height()
        ax.annotate(f'{height:.1f}', xy=(bar.get_x() + bar.get_width()/2, height),
                   xytext=(0, 3), textcoords="offset points", ha='center', va='bottom', fontsize=8)

    plt.tight_layout()
    chart_path_a_bar = OUTPUT_DIR / 'chart_strategy_a_metrics.png'
    plt.savefig(chart_path_a_bar, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()
    charts['metrics_a'] = str(chart_path_a_bar)

    # 4. 전략 B TOP 10 팩터 점수 바 차트
    fig, ax = plt.subplots(figsize=(10, 6))
    stocks_b = ['에이피알', '플리토', '달바글로벌', '감성코퍼레이션', '한화비전',
                '글로벌텍스프리', '카페24', '데브시스터즈', '제닉', '브이티']
    quality_scores = [4.67, 3.07, 3.09, 2.31, 0.05, 1.95, 2.02, 1.95, 1.92, 1.86]
    value_scores = [-1.56, -0.31, -0.44, 0.23, 2.42, 0.37, 0.30, 0.34, 0.29, 0.34]

    x = np.arange(len(stocks_b))
    width = 0.35

    bars1 = ax.bar(x - width/2, quality_scores, width, label='퀄리티 점수', color='#27ae60')
    bars2 = ax.bar(x + width/2, value_scores, width, label='밸류 점수', color='#f39c12')

    ax.set_ylabel('Z-Score', fontsize=12)
    ax.set_title('전략 B TOP 10 종목 - 팩터 점수', fontsize=14, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(stocks_b, rotation=45, ha='right', fontsize=10)
    ax.legend(loc='upper right')
    ax.axhline(y=0, color='gray', linestyle='--', linewidth=0.5)

    plt.tight_layout()
    chart_path_b_bar = OUTPUT_DIR / 'chart_strategy_b_metrics.png'
    plt.savefig(chart_path_b_bar, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()
    charts['metrics_b'] = str(chart_path_b_bar)

    # 5. 공통 종목 비교 차트
    fig, ax = plt.subplots(figsize=(8, 5))
    common_stocks = ['브이티', '제닉', '제룡전기', 'SOOP']
    rank_a = [1, 2, 6, 7]
    rank_b = [10, 9, 13, 14]

    x = np.arange(len(common_stocks))
    width = 0.35

    bars1 = ax.bar(x - width/2, rank_a, width, label='전략 A 순위', color='#3498db')
    bars2 = ax.bar(x + width/2, rank_b, width, label='전략 B 순위', color='#e74c3c')

    ax.set_ylabel('순위 (낮을수록 좋음)', fontsize=12)
    ax.set_title('공통 선정 종목 - 전략별 순위 비교', fontsize=14, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(common_stocks, fontsize=11)
    ax.legend(loc='upper left')
    ax.set_ylim(0, 20)
    ax.invert_yaxis()

    for bar in bars1:
        height = bar.get_height()
        ax.annotate(f'{int(height)}위', xy=(bar.get_x() + bar.get_width()/2, height),
                   xytext=(0, -15), textcoords="offset points", ha='center', va='top', fontsize=10, color='white', fontweight='bold')
    for bar in bars2:
        height = bar.get_height()
        ax.annotate(f'{int(height)}위', xy=(bar.get_x() + bar.get_width()/2, height),
                   xytext=(0, -15), textcoords="offset points", ha='center', va='top', fontsize=10, color='white', fontweight='bold')

    plt.tight_layout()
    chart_path_common = OUTPUT_DIR / 'chart_common_stocks.png'
    plt.savefig(chart_path_common, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()
    charts['common'] = str(chart_path_common)

    # 6. 팩터 구성 개념도
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    # 전략 A
    ax1 = axes[0]
    ax1.set_xlim(0, 10)
    ax1.set_ylim(0, 10)
    ax1.add_patch(plt.Rectangle((1, 3), 3.5, 4, facecolor='#3498db', alpha=0.8))
    ax1.add_patch(plt.Rectangle((5.5, 3), 3.5, 4, facecolor='#e74c3c', alpha=0.8))
    ax1.text(2.75, 5, 'Value\n(이익수익률)', ha='center', va='center', fontsize=12, color='white', fontweight='bold')
    ax1.text(7.25, 5, 'Quality\n(ROC)', ha='center', va='center', fontsize=12, color='white', fontweight='bold')
    ax1.text(5, 8.5, '전략 A: 마법공식', ha='center', va='center', fontsize=14, fontweight='bold')
    ax1.text(5, 1.5, '순위 합산 → 낮은 순위 선정', ha='center', va='center', fontsize=10, style='italic')
    ax1.axis('off')

    # 전략 B
    ax2 = axes[1]
    ax2.set_xlim(0, 10)
    ax2.set_ylim(0, 10)
    ax2.add_patch(plt.Rectangle((0.5, 3), 2.5, 4, facecolor='#f39c12', alpha=0.8))
    ax2.add_patch(plt.Rectangle((3.5, 3), 2.5, 4, facecolor='#27ae60', alpha=0.8))
    ax2.add_patch(plt.Rectangle((6.5, 3), 2.5, 4, facecolor='#9b59b6', alpha=0.8))
    ax2.text(1.75, 5, 'Value\n(PER,PBR\nPCR,PSR)', ha='center', va='center', fontsize=10, color='white', fontweight='bold')
    ax2.text(4.75, 5, 'Quality\n(ROE,GPA\nCFO)', ha='center', va='center', fontsize=10, color='white', fontweight='bold')
    ax2.text(7.75, 5, 'Momentum\n(12-1M)', ha='center', va='center', fontsize=10, color='white', fontweight='bold')
    ax2.text(5, 8.5, '전략 B: 멀티팩터', ha='center', va='center', fontsize=14, fontweight='bold')
    ax2.text(5, 1.5, 'Z-Score 평균 → 높은 점수 선정', ha='center', va='center', fontsize=10, style='italic')
    ax2.axis('off')

    plt.tight_layout()
    chart_path_concept = OUTPUT_DIR / 'chart_factor_concept.png'
    plt.savefig(chart_path_concept, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()
    charts['concept'] = str(chart_path_concept)

    return charts


def create_pdf_report(charts):
    """PDF 보고서 생성"""

    pdf_path = OUTPUT_DIR / 'Quant_Portfolio_Report_2026Q1.pdf'
    doc = SimpleDocTemplate(str(pdf_path), pagesize=A4,
                           rightMargin=1.5*cm, leftMargin=1.5*cm,
                           topMargin=1.5*cm, bottomMargin=1.5*cm)

    # 스타일 정의
    styles = getSampleStyleSheet()

    # 커스텀 스타일
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Title'],
        fontName=FONT_BOLD,
        fontSize=24,
        textColor=COLORS['primary'],
        spaceAfter=30,
        alignment=TA_CENTER,
    )

    heading1_style = ParagraphStyle(
        'CustomHeading1',
        parent=styles['Heading1'],
        fontName=FONT_BOLD,
        fontSize=16,
        textColor=COLORS['primary'],
        spaceBefore=20,
        spaceAfter=12,
        borderColor=COLORS['primary'],
        borderWidth=2,
        borderPadding=5,
    )

    heading2_style = ParagraphStyle(
        'CustomHeading2',
        parent=styles['Heading2'],
        fontName=FONT_BOLD,
        fontSize=13,
        textColor=COLORS['secondary'],
        spaceBefore=15,
        spaceAfter=8,
    )

    body_style = ParagraphStyle(
        'CustomBody',
        parent=styles['Normal'],
        fontName=FONT_NAME,
        fontSize=10,
        textColor=COLORS['dark'],
        spaceAfter=8,
        leading=14,
    )

    bullet_style = ParagraphStyle(
        'CustomBullet',
        parent=styles['Normal'],
        fontName=FONT_NAME,
        fontSize=10,
        textColor=COLORS['dark'],
        leftIndent=20,
        spaceAfter=4,
        leading=14,
    )

    # 문서 구성 요소
    story = []

    # ===== 표지 =====
    story.append(Spacer(1, 2*inch))
    story.append(Paragraph("한국 주식 퀀트 투자 전략", title_style))
    story.append(Paragraph("포트폴리오 보고서", title_style))
    story.append(Spacer(1, 0.5*inch))

    subtitle_style = ParagraphStyle(
        'Subtitle',
        fontName=FONT_NAME,
        fontSize=14,
        textColor=COLORS['secondary'],
        alignment=TA_CENTER,
        spaceAfter=10,
    )
    story.append(Paragraph("2026년 1분기 (2025년 3분기 재무제표 기준)", subtitle_style))
    story.append(Paragraph("유효 기간: 2026.01 ~ 2026.03", subtitle_style))

    story.append(Spacer(1, 1*inch))

    # 요약 박스
    summary_data = [
        ['기준일', '2026년 1월 29일'],
        ['재무제표', '2025년 3분기 (TTM 방식)'],
        ['유니버스', 'KOSPI + KOSDAQ 668개 종목'],
        ['전략 A', '마법공식 (Value + Quality)'],
        ['전략 B', '멀티팩터 (Value + Quality + Momentum)'],
        ['포트폴리오', '각 전략별 TOP 20 종목'],
    ]

    summary_table = Table(summary_data, colWidths=[3*cm, 10*cm])
    summary_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), FONT_NAME),
        ('FONTNAME', (0, 0), (0, -1), FONT_BOLD),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('TEXTCOLOR', (0, 0), (0, -1), COLORS['primary']),
        ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(summary_table)

    story.append(Spacer(1, 1.5*inch))

    date_style = ParagraphStyle(
        'Date',
        fontName=FONT_NAME,
        fontSize=11,
        textColor=COLORS['dark'],
        alignment=TA_CENTER,
    )
    story.append(Paragraph(f"작성일: {datetime.now().strftime('%Y년 %m월 %d일')}", date_style))

    story.append(PageBreak())

    # ===== 목차 =====
    story.append(Paragraph("목차", heading1_style))
    story.append(Spacer(1, 0.3*inch))

    toc_items = [
        "1. 프로젝트 개요",
        "2. 백테스팅 조건",
        "3. 전략 설명",
        "4. 전략 A (마법공식) 포트폴리오",
        "5. 전략 B (멀티팩터) 포트폴리오",
        "6. 공통 선정 종목 분석",
        "7. 투자 시 유의사항",
    ]

    for item in toc_items:
        story.append(Paragraph(item, body_style))

    story.append(PageBreak())

    # ===== 1. 프로젝트 개요 =====
    story.append(Paragraph("1. 프로젝트 개요", heading1_style))

    story.append(Paragraph("1.1 목적", heading2_style))
    story.append(Paragraph(
        "본 프로젝트는 한국 주식시장(KOSPI + KOSDAQ)에서 검증된 퀀트 투자 전략을 적용하여 "
        "체계적이고 감정에 휘둘리지 않는 투자 포트폴리오를 구성하는 것을 목표로 합니다.",
        body_style
    ))

    story.append(Paragraph("1.2 핵심 전략", heading2_style))
    story.append(Paragraph("• <b>전략 A (마법공식)</b>: 조엘 그린블라트의 Magic Formula 기반, Value + Quality 결합", bullet_style))
    story.append(Paragraph("• <b>전략 B (멀티팩터)</b>: 학술 연구 기반 다중 팩터 모델, Value + Quality + Momentum 결합", bullet_style))

    story.append(Paragraph("1.3 데이터 소스", heading2_style))
    story.append(Paragraph("• <b>시장 데이터</b>: pykrx (KRX 공식 API)", bullet_style))
    story.append(Paragraph("• <b>재무제표</b>: FnGuide Company Guide (TTM 방식 적용)", bullet_style))
    story.append(Paragraph("• <b>기준일</b>: 2025년 3분기 재무제표 (2025-09-30)", bullet_style))

    # 팩터 개념도 이미지
    story.append(Spacer(1, 0.3*inch))
    if 'concept' in charts:
        img = Image(charts['concept'], width=16*cm, height=6.5*cm)
        story.append(img)

    story.append(PageBreak())

    # ===== 2. 백테스팅 조건 =====
    story.append(Paragraph("2. 백테스팅 조건", heading1_style))

    story.append(Paragraph("2.1 유니버스 필터링", heading2_style))

    filter_data = [
        ['조건', '기준', '목적'],
        ['시가총액', '≥ 1,000억원', '유동성 확보, 소형주 제외'],
        ['거래대금', '≥ 50억원 (일평균)', '충분한 유동성 확보'],
        ['업종 제외', '금융, 지주, SPAC, 리츠', '특수 구조 기업 제외'],
        ['재무 필터', '자본 > 0', '자본잠식 기업 제외'],
        ['데이터', 'FnGuide 재무제표 존재', '분석 가능 종목만'],
    ]

    filter_table = Table(filter_data, colWidths=[3*cm, 4*cm, 7*cm])
    filter_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), FONT_BOLD),
        ('FONTNAME', (0, 1), (-1, -1), FONT_NAME),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BACKGROUND', (0, 0), (-1, 0), COLORS['primary']),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, COLORS['light']),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, COLORS['light']]),
    ]))
    story.append(filter_table)

    story.append(Paragraph("2.2 필터링 결과", heading2_style))
    story.append(Paragraph("• 전체 상장 종목: 2,773개", bullet_style))
    story.append(Paragraph("• 필터 통과 종목: 668개 (24.1%)", bullet_style))
    story.append(Paragraph("• 재무제표 확보: 약 700개 종목 (캐시 데이터)", bullet_style))

    story.append(Paragraph("2.3 TTM (Trailing Twelve Months) 방식", heading2_style))
    story.append(Paragraph(
        "최근 4분기 데이터를 합산하여 가장 최신의 연간 실적을 반영합니다. "
        "이는 연간 재무제표보다 더 시의성 있는 분석을 가능하게 합니다.",
        body_style
    ))
    story.append(Paragraph("• <b>Flow 계정</b> (손익/현금흐름): 최근 4분기 합산", bullet_style))
    story.append(Paragraph("• <b>Stock 계정</b> (재무상태표): 최신 분기 값 사용", bullet_style))

    story.append(PageBreak())

    # ===== 3. 전략 설명 =====
    story.append(Paragraph("3. 전략 설명", heading1_style))

    story.append(Paragraph("3.1 전략 A: 마법공식 (Magic Formula)", heading2_style))
    story.append(Paragraph(
        "조엘 그린블라트가 개발한 투자 전략으로, '좋은 기업을 싼 가격에 사는' 원칙을 "
        "계량화한 방법입니다. Value와 Quality 두 가지 팩터를 결합합니다.",
        body_style
    ))

    formula_a_data = [
        ['지표', '산식', '의미'],
        ['이익수익률\n(Earnings Yield)', 'EBIT / EV\n\nEV = 시가총액 + 총부채 - 여유자금', '기업가치 대비 수익 창출력\n(높을수록 저평가)'],
        ['투하자본수익률\n(ROC)', 'EBIT / IC\n\nIC = 순운전자본 + 순고정자산', '투자 자본 대비 수익률\n(높을수록 효율적)'],
    ]

    formula_a_table = Table(formula_a_data, colWidths=[3.5*cm, 5.5*cm, 5*cm])
    formula_a_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), FONT_BOLD),
        ('FONTNAME', (0, 1), (-1, -1), FONT_NAME),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BACKGROUND', (0, 0), (-1, 0), COLORS['secondary']),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, COLORS['light']),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
    ]))
    story.append(formula_a_table)

    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph("3.2 전략 B: 멀티팩터 (Multi-Factor)", heading2_style))
    story.append(Paragraph(
        "학술 연구에서 검증된 여러 팩터를 결합한 전략입니다. "
        "Value, Quality, Momentum 세 가지 카테고리의 팩터를 Z-Score로 표준화하여 합산합니다.",
        body_style
    ))

    formula_b_data = [
        ['카테고리', '팩터', '산식', '방향'],
        ['Value', 'PER', '시가총액 / 당기순이익', '낮을수록 ↑'],
        ['Value', 'PBR', '시가총액 / 자본', '낮을수록 ↑'],
        ['Value', 'PCR', '시가총액 / 영업현금흐름', '낮을수록 ↑'],
        ['Value', 'PSR', '시가총액 / 매출액', '낮을수록 ↑'],
        ['Quality', 'ROE', '당기순이익 / 자본 × 100', '높을수록 ↑'],
        ['Quality', 'GPA', '매출총이익 / 자산 × 100', '높을수록 ↑'],
        ['Quality', 'CFO', '영업현금흐름 / 자산 × 100', '높을수록 ↑'],
        ['Momentum', '12-1M', '12개월 수익률 - 1개월 수익률', '높을수록 ↑'],
    ]

    formula_b_table = Table(formula_b_data, colWidths=[2.5*cm, 2*cm, 6*cm, 2.5*cm])
    formula_b_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), FONT_BOLD),
        ('FONTNAME', (0, 1), (-1, -1), FONT_NAME),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BACKGROUND', (0, 0), (-1, 0), COLORS['secondary']),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, COLORS['light']),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('SPAN', (0, 1), (0, 4)),  # Value 병합
        ('SPAN', (0, 5), (0, 7)),  # Quality 병합
    ]))
    story.append(formula_b_table)

    story.append(PageBreak())

    # ===== 4. 전략 A 포트폴리오 =====
    story.append(Paragraph("4. 전략 A (마법공식) 포트폴리오", heading1_style))

    # 차트 이미지
    if 'metrics_a' in charts:
        img = Image(charts['metrics_a'], width=15*cm, height=9*cm)
        story.append(img)

    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph("4.1 TOP 20 종목 및 선정 이유", heading2_style))

    # 전략 A TOP 20 테이블
    strategy_a_data = [
        ['순위', '종목코드', '종목명', '이익수익률', 'ROC', '선정 이유'],
        ['1', '018290', '브이티', '15.6%', '44.9%', 'K-뷰티, 최고 자본효율'],
        ['2', '123330', '제닉', '13.0%', '54.0%', '화장품 소재, 최고 ROC'],
        ['3', '340570', '티앤엘', '13.8%', '29.9%', '의료기기, 안정 수익'],
        ['4', '200670', '휴메딕스', '15.4%', '26.5%', '헬스케어, 고이익률'],
        ['5', '383220', 'F&F', '14.8%', '25.6%', '패션, 브랜드파워'],
        ['6', '033100', '제룡전기', '10.7%', '33.3%', '전력설비, 고자본효율'],
        ['7', '067160', 'SOOP', '11.5%', '27.8%', '스트리밍, 성장+수익'],
        ['8', '035900', 'JYP Ent.', '8.8%', '38.2%', '엔터, 높은 ROC'],
        ['9', '402340', 'SK스퀘어', '10.3%', '28.1%', '투자회사, 지분가치'],
        ['10', '259960', '크래프톤', '12.5%', '21.3%', '게임, 현금창출'],
        ['11', '041510', '에스엠', '10.8%', '23.6%', '엔터, 안정 수익'],
        ['12', '439260', '대한조선', '10.0%', '27.7%', '조선, 수주 호조'],
        ['13', '271560', '오리온', '14.7%', '18.7%', '제과, 중국 호조'],
        ['14', '037460', '삼지전자', '13.8%', '18.5%', '전자부품, 원가경쟁'],
        ['15', '190510', '나무가', '10.6%', '22.1%', 'IT솔루션'],
        ['16', '033500', '동성화인텍', '7.8%', '32.8%', '건자재, 고자본효율'],
        ['17', '250060', '모비스', '8.1%', '30.6%', 'SW, 현금자산 풍부'],
        ['18', '001060', 'JW중외제약', '9.4%', '24.1%', '제약, 안정'],
        ['19', '052400', '코나아이', '7.3%', '34.4%', '핀테크, 높은 ROC'],
        ['20', '160980', '싸이맥스', '21.5%', '16.7%', '반도체장비, 최고 이익률'],
    ]

    strategy_a_table = Table(strategy_a_data, colWidths=[1*cm, 1.8*cm, 2.5*cm, 2*cm, 1.8*cm, 4.5*cm])
    strategy_a_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), FONT_BOLD),
        ('FONTNAME', (0, 1), (-1, -1), FONT_NAME),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BACKGROUND', (0, 0), (-1, 0), COLORS['primary']),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (-1, 1), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, COLORS['light']),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, COLORS['light']]),
    ]))
    story.append(strategy_a_table)

    # 섹터 분포
    story.append(Spacer(1, 0.3*inch))
    if 'sector_a' in charts:
        story.append(Paragraph("4.2 섹터 분포", heading2_style))
        img = Image(charts['sector_a'], width=12*cm, height=7.5*cm)
        story.append(img)

    story.append(PageBreak())

    # ===== 5. 전략 B 포트폴리오 =====
    story.append(Paragraph("5. 전략 B (멀티팩터) 포트폴리오", heading1_style))

    # 차트 이미지
    if 'metrics_b' in charts:
        img = Image(charts['metrics_b'], width=15*cm, height=9*cm)
        story.append(img)

    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph("5.1 TOP 20 종목 및 선정 이유", heading2_style))

    # 전략 B TOP 20 테이블
    strategy_b_data = [
        ['순위', '종목코드', '종목명', '멀티팩터', '퀄리티', '선정 이유'],
        ['1', '278470', '에이피알', '1.04', '4.67', 'ROE 67%, GPA 150%'],
        ['2', '300080', '플리토', '0.92', '3.07', 'AI번역, 고수익성'],
        ['3', '483650', '달바글로벌', '0.88', '3.09', 'K-뷰티, 수출 호조'],
        ['4', '036620', '감성코퍼레이션', '0.85', '2.31', '패션(스파오), 균형'],
        ['5', '489790', '한화비전', '0.82', '0.05', '보안장비, 저평가'],
        ['6', '204620', '글로벌텍스프리', '0.77', '1.95', '세금환급, 독점구조'],
        ['7', '042000', '카페24', '0.77', '2.02', '이커머스 플랫폼'],
        ['8', '194480', '데브시스터즈', '0.76', '1.95', '게임(쿠키런)'],
        ['9', '123330', '제닉', '0.73', '1.92', '화장품 소재'],
        ['10', '018290', '브이티', '0.73', '1.86', 'K-뷰티, 고효율'],
        ['11', '039130', '하나투어', '0.71', '2.16', '여행업, ROE 47%'],
        ['12', '215200', '메가스터디교육', '0.64', '1.48', '교육업, 저평가'],
        ['13', '033100', '제룡전기', '0.60', '1.47', '전력설비, 균형'],
        ['14', '067160', 'SOOP', '0.60', '1.41', '스트리밍, 현금창출'],
        ['15', '095660', '네오위즈', '0.57', '1.30', '게임, 저평가'],
        ['16', '336570', '원텍', '0.55', '1.42', '의료기기'],
        ['17', '053800', '안랩', '0.54', '1.23', '보안SW, 안정'],
        ['18', '000660', 'SK하이닉스', '0.53', '1.85', '반도체, HBM 수혜'],
        ['19', '214180', '헥토이노베이션', '0.53', '1.16', '핀테크, 저평가'],
        ['20', '403870', 'HPSP', '0.53', '1.74', '반도체장비, 고수익'],
    ]

    strategy_b_table = Table(strategy_b_data, colWidths=[1*cm, 1.8*cm, 3*cm, 1.8*cm, 1.8*cm, 4*cm])
    strategy_b_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), FONT_BOLD),
        ('FONTNAME', (0, 1), (-1, -1), FONT_NAME),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BACKGROUND', (0, 0), (-1, 0), COLORS['primary']),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (-1, 1), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, COLORS['light']),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, COLORS['light']]),
    ]))
    story.append(strategy_b_table)

    # 섹터 분포
    story.append(Spacer(1, 0.3*inch))
    if 'sector_b' in charts:
        story.append(Paragraph("5.2 섹터 분포", heading2_style))
        img = Image(charts['sector_b'], width=12*cm, height=7.5*cm)
        story.append(img)

    story.append(PageBreak())

    # ===== 6. 공통 선정 종목 =====
    story.append(Paragraph("6. 공통 선정 종목 분석", heading1_style))

    story.append(Paragraph(
        "두 전략 모두에서 TOP 20에 선정된 종목은 Value와 Quality 두 측면에서 "
        "모두 우수한 기업입니다. 이러한 종목들은 더 높은 신뢰도를 가집니다.",
        body_style
    ))

    # 공통 종목 차트
    if 'common' in charts:
        story.append(Spacer(1, 0.2*inch))
        img = Image(charts['common'], width=12*cm, height=7.5*cm)
        story.append(img)

    story.append(Spacer(1, 0.3*inch))
    story.append(Paragraph("6.1 공통 종목 상세 분석", heading2_style))

    common_data = [
        ['종목명', '전략A\n순위', '전략B\n순위', '핵심 강점'],
        ['브이티\n(018290)', '1위', '10위', '• K-뷰티 대표주, 일본 수출 호조\n• 이익수익률 15.6%, ROC 44.9%\n• ROE 36.4%, 높은 자본효율'],
        ['제닉\n(123330)', '2위', '9위', '• 화장품 소재 전문, 마진율 우수\n• 업계 최고 ROC 54%\n• GPA 50.6%, 자산 활용도 높음'],
        ['제룡전기\n(033100)', '6위', '13위', '• 전력설비, 에너지 전환 수혜\n• ROC 33.3%, 안정적 수익구조\n• Value + Quality 균형'],
        ['SOOP\n(067160)', '7위', '14위', '• 스트리밍 플랫폼 (구 아프리카TV)\n• 성장성과 수익성 동시 보유\n• ROE 21.4%, 현금흐름 우수'],
    ]

    common_table = Table(common_data, colWidths=[2.5*cm, 1.5*cm, 1.5*cm, 9*cm])
    common_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), FONT_BOLD),
        ('FONTNAME', (0, 1), (-1, -1), FONT_NAME),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BACKGROUND', (0, 0), (-1, 0), COLORS['accent']),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (2, -1), 'CENTER'),
        ('ALIGN', (3, 1), (3, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, COLORS['light']),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, COLORS['light']]),
    ]))
    story.append(common_table)

    story.append(PageBreak())

    # ===== 7. 유의사항 =====
    story.append(Paragraph("7. 투자 시 유의사항", heading1_style))

    story.append(Paragraph("7.1 포트폴리오 유효 기간", heading2_style))
    story.append(Paragraph("• <b>적용 기간</b>: 2026년 1월 ~ 2026년 3월", bullet_style))
    story.append(Paragraph("• <b>재조정 시점</b>: 2025년 4분기 재무제표 발표 후 (2026년 3월 말 예정)", bullet_style))
    story.append(Paragraph("• 분기별 리밸런싱을 권장하며, 재무제표 발표 후 1~2주 내 조정 필요", bullet_style))

    story.append(Paragraph("7.2 투자 위험", heading2_style))

    risk_data = [
        ['위험 유형', '설명', '대응 방안'],
        ['시장 위험', '전체 시장 하락 시 포트폴리오도 하락', '분산 투자, 현금 비중 조절'],
        ['개별 종목 위험', '특정 종목의 급격한 하락', 'TOP 20 동일 가중 투자'],
        ['유동성 위험', '매매 시 호가 스프레드 발생', '거래대금 50억 이상 필터'],
        ['모멘텀 미반영', '단기 추세 변화 반영 부족', '별도 모멘텀 모니터링'],
    ]

    risk_table = Table(risk_data, colWidths=[3*cm, 6*cm, 5*cm])
    risk_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), FONT_BOLD),
        ('FONTNAME', (0, 1), (-1, -1), FONT_NAME),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BACKGROUND', (0, 0), (-1, 0), COLORS['danger']),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, COLORS['light']),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(risk_table)

    story.append(Paragraph("7.3 투자 제안", heading2_style))
    story.append(Paragraph("• <b>보수적 투자자</b>: 전략 A 단독 또는 공통 종목 4개 집중 투자", bullet_style))
    story.append(Paragraph("• <b>균형 투자자</b>: 전략 A 50% + 전략 B 50% 혼합", bullet_style))
    story.append(Paragraph("• <b>공격적 투자자</b>: 전략 B 중심 + 모멘텀 추가 고려", bullet_style))

    story.append(Spacer(1, 0.5*inch))

    # 면책 조항
    disclaimer_style = ParagraphStyle(
        'Disclaimer',
        fontName=FONT_NAME,
        fontSize=8,
        textColor=colors.gray,
        alignment=TA_CENTER,
        spaceBefore=20,
    )
    story.append(Paragraph(
        "본 보고서는 정보 제공 목적으로 작성되었으며, 투자 권유가 아닙니다. "
        "투자에 따른 손실은 투자자 본인에게 귀속됩니다. "
        "과거 성과가 미래 수익을 보장하지 않습니다.",
        disclaimer_style
    ))

    story.append(Spacer(1, 0.3*inch))
    story.append(Paragraph(
        f"Generated by Claude Code | {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        disclaimer_style
    ))

    # PDF 생성
    doc.build(story)

    return pdf_path


def main():
    print("=" * 60)
    print("퀀트 투자 전략 포트폴리오 보고서 PDF 생성")
    print("=" * 60)

    print("\n[1/2] 차트 생성 중...")
    charts = create_charts()
    print(f"  - 생성된 차트: {len(charts)}개")

    print("\n[2/2] PDF 보고서 생성 중...")
    pdf_path = create_pdf_report(charts)
    print(f"  - 저장 위치: {pdf_path}")

    print("\n" + "=" * 60)
    print("PDF 보고서 생성 완료!")
    print("=" * 60)

    return pdf_path


if __name__ == '__main__':
    main()
