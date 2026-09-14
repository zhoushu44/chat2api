#!/bin/bash
export SSHPASS='6Qz6ao0T1zvL'
sshpass -e ssh -o StrictHostKeyChecking=no root@192.6.121.16 bash -s <<'EOF'
echo "=== 内存/MEM ==="; free -m
echo "=== 负载 ==="; uptime
echo "=== 磁盘 ==="; df -h / | tail -1
echo "=== Docker 容器 ==="; docker ps --format '{{.Names}}\t{{.Status}}'
echo "=== Docker 资源占用 ==="; docker stats --no-stream --format '{{.Name}}\tCPU={{.CPUPerc}}\tMEM={{.MemUsage}}'
EOF
