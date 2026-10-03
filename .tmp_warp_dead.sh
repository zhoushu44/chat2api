#!/bin/bash
set -u
echo "=== 1. 死掉的 sing-box 实例清单（meta.pid 不存在） ==="
DEAD=""
for idx in $(seq 0 99); do
  M=/root/warp-instances/warp-$idx/meta.json
  [ -f "$M" ] || continue
  PID=$(grep -oE '"pid"[[:space:]]*:[[:space:]]*[0-9]+' "$M" | grep -oE '[0-9]+$')
  PORT=$((10010 + idx))
  if [ -n "$PID" ]; then
    if ! docker exec warp sh -c "ls -d /proc/$PID" >/dev/null 2>&1; then
      DEAD="$DEAD $idx"
    fi
  fi
done
echo "dead instances:$DEAD"
echo "count: $(echo $DEAD | wc -w)"
echo ""
echo "=== 2. 这些实例的 singbox.log 死亡前最后几行 ==="
for idx in $(echo $DEAD | awk '{print $1, $2}'); do
  echo "--- warp-$idx ---"
  tail -3 /root/warp-instances/warp-$idx/singbox.log 2>/dev/null | tail -2
done
echo ""
echo "=== 3. 池子里这些实例的状态 ==="
curl -s --max-time 10 "http://195.72.185.32:4433/api/pool/status" | tr '{' '\n' | grep -E '"host_port":100(12|13|15) ' | grep -oE '"host_port":[0-9]+|"health":"[^"]*"|"status":"[^"]*"'
echo ""
echo "=== 4. 容器内 /proc 总数 vs 期望 ==="
docker exec warp sh -c "ls /proc | grep -cE '^[0-9]+$'"
echo "(100 sing-box + 100 usque + node ≈ 210)"
