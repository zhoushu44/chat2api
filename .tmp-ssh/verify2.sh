#!/bin/bash
export SSHPASS='6Qz6ao0T1zvL'
sshpass -e ssh -o StrictHostKeyChecking=no -p 22 root@192.6.121.16 bash -s <<'EOF'
# web 403 可能是鉴权；带 token 试（从宿主机找之前的调用方式）
curl -s -o /dev/null -w "root: %{http_code}\n" http://127.0.0.1:3077/
# 找数据目录
docker exec chatgpt2api-10 sh -c "find / -name 'accounts.json' -not -path '/proc/*' 2>/dev/null | head -3"
# go 服务日志
docker logs chatgpt2api-10 2>&1 | grep -v regiforge | tail -8
EOF
