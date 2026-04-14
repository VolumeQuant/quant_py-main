"""각 방안별 2018 whipsaw 건수 감소 효과 시뮬 (BT 전 순수 regime 시뮬)
방안: A(버퍼), B(쿨다운), C(확인일수), A+B, A+C, B+C, A+B+C
"""
import pandas as pd
import numpy as np

df = pd.read_parquet('C:/dev/data_cache/kospi_yf.parquet')
kospi = df.iloc[:, 0].fillna(df['kospi']).sort_index().rename('close')
ma200 = kospi.rolling(200).mean()


def apply_regime(kospi, ma200, confirm_days=5, buffer_pct=0.0, cooldown_days=0):
    """국면 판정 규칙: 확인일수 + 버퍼 + 쿨다운"""
    gap_pct = (kospi - ma200) / ma200
    upper = buffer_pct / 100
    lower = -buffer_pct / 100

    # raw_signal: 1=attack(gap>+buf), 0=defense(gap<-buf), -1=유지(데드존)
    raw = pd.Series(-1, index=kospi.index)
    raw[gap_pct > upper] = 1
    raw[gap_pct < lower] = 0

    regime = []
    current = None
    streak = 0
    streak_mode = None
    last_switch_idx = -99999

    for i, sig in enumerate(raw):
        # 데드존이면 streak 끊지 않고 유지 (현재 mode 계속)
        if sig == -1:
            regime.append(current)
            continue
        # 신호
        if sig == streak_mode:
            streak += 1
        else:
            streak = 1
            streak_mode = sig

        # 초기화
        if current is None:
            if streak >= confirm_days:
                current = int(sig)
                last_switch_idx = i
            regime.append(current)
            continue

        # 전환 가능 여부
        if streak >= confirm_days and current != sig:
            # 쿨다운 체크
            if (i - last_switch_idx) >= cooldown_days:
                current = int(sig)
                last_switch_idx = i
        regime.append(current)

    return pd.Series(regime, index=raw.index)


def count_transitions(regime, year=None):
    """전환 이벤트 추출"""
    s = regime.dropna()
    transitions = []
    prev = None
    for dt, r in s.items():
        if prev is not None and r != prev:
            transitions.append({'date': dt, 'from': prev, 'to': r})
        prev = r
    tr = pd.DataFrame(transitions)
    if tr.empty:
        return tr, 0, 0
    tr['gap'] = tr['date'].diff().dt.days
    if year is not None:
        tr = tr[tr['date'].dt.year == year]
    whipsaw = int((tr['gap'] <= 60).sum())
    return tr, len(tr), whipsaw


# ═══ 방안별 테스트 ═══
scenarios = [
    # (label, confirm, buffer, cooldown)
    ('기본 (C5 / B0% / CD0)', 5, 0.0, 0),
    # C: 확인일수만
    ('C=3', 3, 0.0, 0),
    ('C=7', 7, 0.0, 0),
    ('C=10', 10, 0.0, 0),
    ('C=15', 15, 0.0, 0),
    ('C=20', 20, 0.0, 0),
    # A: 버퍼만
    ('B=1%', 5, 1.0, 0),
    ('B=2%', 5, 2.0, 0),
    ('B=3%', 5, 3.0, 0),
    ('B=5%', 5, 5.0, 0),
    # B: 쿨다운만
    ('CD=15', 5, 0.0, 15),
    ('CD=20', 5, 0.0, 20),
    ('CD=30', 5, 0.0, 30),
    ('CD=40', 5, 0.0, 40),
    # C+A
    ('C=10 + B=2%', 10, 2.0, 0),
    ('C=10 + B=3%', 10, 3.0, 0),
    # C+B
    ('C=10 + CD=20', 10, 0.0, 20),
    ('C=10 + CD=30', 10, 0.0, 30),
    # A+B
    ('B=2% + CD=30', 5, 2.0, 30),
    ('B=3% + CD=30', 5, 3.0, 30),
    # C+A+B
    ('C=10 + B=2% + CD=20', 10, 2.0, 20),
    ('C=10 + B=3% + CD=30', 10, 3.0, 30),
    ('C=15 + B=3% + CD=20', 15, 3.0, 20),
]

print(f'{"시나리오":<30} {"전체전환":>8} {"전체whipsaw":>12} {"2018전환":>8} {"2018whipsaw":>12}')
print('-' * 85)
results = []
for label, cd, buf, cdd in scenarios:
    reg = apply_regime(kospi, ma200, confirm_days=cd, buffer_pct=buf, cooldown_days=cdd)
    tr_all, n_all, w_all = count_transitions(reg, year=None)
    tr_18, n_18, w_18 = count_transitions(reg, year=2018)
    print(f'{label:<30} {n_all:>8} {w_all:>12} {n_18:>8} {w_18:>12}')
    results.append({'scenario': label, 'confirm': cd, 'buffer': buf, 'cooldown': cdd,
                    'total_trans': n_all, 'total_whipsaw': w_all,
                    '2018_trans': n_18, '2018_whipsaw': w_18})

pd.DataFrame(results).to_csv('C:/dev/data_cache/whipsaw_reduction_sim.csv', index=False, encoding='utf-8-sig')
print('\n저장: whipsaw_reduction_sim.csv')
