#!/bin/bash
set -u
echo "=== regiforge 代码在容器里如何装进去的 ==="
docker exec chatgpt2api-13 sh -c "cat /proc/mounts | grep -i regiforge; ls -la /opt/ | head"
echo ""
echo "=== 容器内 provider.py 是否与本地 chat2api 仓库一致 ==="
docker exec chatgpt2api-13 md5sum /opt/regiforge/projects/chatgpt_register/steps/_sentinel_v8.py /opt/regiforge/projects/chatgpt_register/steps/_http_engine.py 2>/dev/null
echo ""
echo "=== warp 管理进程怎么跑的（容器内 or 宿主） ==="
ps aux | grep -E "server\.cjs|node.*warp" | grep -v grep
docker exec warp sh -c "ps aux 2>/dev/null | head -5" 2>/dev/null
