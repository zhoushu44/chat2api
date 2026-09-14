#!/bin/bash
export SSHPASS='6Qz6ao0T1zvL'
sshpass -e ssh -o StrictHostKeyChecking=no -p 22 root@192.6.121.16 bash -s <<'EOF'
sleep 10
# 健康检查
curl -s -o /dev/null -w "web: %{http_code}\n" http://127.0.0.1:3077/api/accounts
# 账号池数量
docker exec chatgpt2api-10 sh -c "python3 -c \"import json;d=json.load(open('/app/data/accounts.json'));print('accounts:',len(d))\"" 2>/dev/null || \
docker exec chatgpt2api-10 sh -c "ls /app/data/ | head -20"
# 容器日志尾部
docker logs chatgpt2api-10 2>&1 | tail -5
EOF
