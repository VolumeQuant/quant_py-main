"""DEPRECATED — 2026-05-12 사고로 폐기

이 스크립트는 3 worker 병렬 + 호출당 sleep 없음으로
DART 서버의 IP 거부를 유발했습니다.

CLAUDE.md "pykrx 1초 sleep, 순차 실행 절대" 원칙을 DART에도 적용해야 함.

대신 refetch_serial.py 사용:
  python refetch_serial.py
"""
import sys
print("DEPRECATED — refetch_serial.py를 사용하세요")
print("CLAUDE.md: pykrx 1초 sleep, 순차 실행 절대. DART도 동일 원칙")
sys.exit(1)
