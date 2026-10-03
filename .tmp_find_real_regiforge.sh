#!/bin/bash
set -u
echo "=== 独立 regiforge 容器（真正的任务执行者） ==="
docker exec regiforge md5sum /app/proxy/wary/provider.py /app/proxy/socks5/provider.py 2>/dev/null || docker exec regiforge sh -c "find / -maxdepth 3 -name provider.py -path '*wary*' 2>/dev/null | head -3"
echo ""
echo "=== regiforge 容器的代码路径 ==="
docker exec regiforge sh -c "ls /app 2>/dev/null | head -8; pwd"
docker exec regiforge sh -c "ps aux | head -6"
