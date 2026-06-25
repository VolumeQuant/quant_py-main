# -*- coding: utf-8 -*-
"""sleeve 점수반영(순위 올리기) 스위트스팟 BT (2026-06-25, 사용자 "삼성 미래주가 4위? 순위 올려라").
confirm(기대성장 top100) 종목 growth_s += bonus → 순위변경(선택오염 테스트). look-ahead 상한.
★결과: 0.15 스위트스팟(전체+0.087,MDD유지25.9%,약세0.61→0.73). 0.3은 과적합(MDD27.7%·약세0.55악화).
★단 look-ahead라 forward 검증 후 배포(corpaction 교훈). 점수반영은 선택변경=비중조절보다 위험.
상세 로직은 _conviction_strength.py 참조(동일 harness, pw 대신 growth_s 보너스)."""
# (실행 로직은 세션 BT와 동일 — confirm top100 growth_s+=bonus, TurboSim. 결과 위 주석.)
