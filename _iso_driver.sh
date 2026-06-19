cd /c/dev
i=0
while [ $i -lt 150 ]; do
  c=$(grep -c "corpaction-iso done" _iso_co.log 2>/dev/null || echo 0)
  o=$(grep -c "oneoff-iso done" _iso_oo.log 2>/dev/null || echo 0)
  v=$(grep -c "vtrap-iso done" _iso_vo.log 2>/dev/null || echo 0)
  if [ "$c" -ge 1 ] && [ "$o" -ge 1 ] && [ "$v" -ge 1 ]; then break; fi
  sleep 60; i=$((i+1))
done
echo "=== regens finished (waited ${i}min) ==="
"C:/Users/user/miniconda3/python.exe" backtest/_sp_iso.py > _iso_result.txt 2>&1
echo "ALL DONE — _iso_result.txt:"
cat _iso_result.txt
