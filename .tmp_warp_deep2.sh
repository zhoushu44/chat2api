#!/bin/bash
set -u
echo "=== 1. 当前端口监听总数 ==="
CNT=$(ss -tln | grep -oE ':10[01][0-9][0-9]' | sort -u | wc -l)
echo "listening: $CNT / 100"
echo ""
echo "=== 2. 缺失的端口（对照 10010-10109） ==="
for i in $(seq 10 109); do
  if ! ss -tln | grep -q ":100$i\|:10$i " ; then :; fi
done
python3 - << 'PYEOF' 2>/dev/null || true
PYEOF
# 用 bash 对比
MISSING=""
for idx in $(seq 0 99); do
  P=$((10010 + idx))
  if ! ss -tln | grep -q ":$P "; then MISSING="$MISSING $P"; fi
done
echo "missing ports:$MISSING"
echo ""
echo "=== 3. warp-5 (pid 189) 是否真活着 ==="
docker exec warp sh -c "ls -d /proc/189 2>/dev/null && echo 'PID189 ALIVE' || echo 'PID189 DEAD'"
docker exec warp sh -c "cat /root/warp-instances/warp-5/meta.json" 2>/dev/null
echo ""
echo "=== 4. 容器内 sing-box 进程数 ==="
docker exec warp sh -c "ls /proc | grep -E '^[0-9]+$' | while read p; do cat /proc/\$p/cmdline 2>/dev/null | tr '\0' ' '; echo; done | grep -c sing-box"
echo ""
echo "=== 5. 容器内是否有 OOM/被杀记录 ==="
docker inspect warp --format 'OOMKilled={{.State.OOMKilled}} Restarts={{.RestartCount}} ExitCode={{.State.ExitCode}}'
dmesg 2>/dev/null | grep -iE "oom|killed process" | tail -5 || echo "(dmesg 不可读)"
echo ""
echo "=== 6. 系统内存 ==="
free -h | head -3
