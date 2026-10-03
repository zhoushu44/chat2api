#!/bin/bash
set -u
DEAD="2 3 5 7 8 9 10 12 13 14 28 33 39 42 54 61 62 63 64 65"

echo "=== 逐个拉起死掉的 sing-box 实例（串行，间隔 3s，避免资源竞争） ==="
OK=0; FAIL=0
for idx in $DEAD; do
  R=$(curl -s --max-time 20 -X POST "http://195.72.185.32:4433/api/start" \
        -H "Content-Type: application/json" -d "{\"name\":\"warp-$idx\"}")
  if echo "$R" | grep -q '"code":"00000"'; then
    OK=$((OK+1)); echo "warp-$idx: OK"
  else
    FAIL=$((FAIL+1)); echo "warp-$idx: FAIL -> $(echo $R | head -c 120)"
  fi
  sleep 3
done
echo ""
echo "=== 结果: OK=$OK FAIL=$FAIL ==="
echo ""
echo "=== 等 20s 后检查端口 ==="
sleep 20
CNT=$(ss -tln | grep -oE ':10[01][0-9][0-9]' | sort -u | wc -l)
echo "listening: $CNT / 100"
echo ""
echo "=== 池状态 ==="
curl -s --max-time 10 "http://195.72.185.32:4433/api/pool/status" | grep -oE '"total":[0-9]+|"available":[0-9]+|"unhealthy":[0-9]+' | head -3
