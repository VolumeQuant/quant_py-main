#!/bin/bash
# G서브 워커 완료 대기 후 전체 파이프라인 실행
echo "G서브 워커 완료 대기 중..."
while [ $(tasklist 2>/dev/null | grep -c python) -gt 1 ]; do
    sleep 30
done
echo "워커 완료. 파이프라인 시작."
cd /c/dev
/c/Users/user/miniconda3/envs/volumequant/python.exe -u /c/dev/backtest/v77_full_pipeline.py > /c/dev/logs/v77_pipeline.log 2>&1
echo "파이프라인 완료."
