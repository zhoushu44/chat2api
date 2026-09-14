#!/bin/bash
export SSHPASS='6Qz6ao0T1zvL'
sshpass -e ssh -o StrictHostKeyChecking=no -p 22 root@192.6.121.16 bash -s <<'EOF'
# 验证账号池数量完整（升级前是 143）
docker exec chatgpt2api-10 sh -c "python3 -c \"import json; d=json.load(open('/data/accounts.json')); print('accounts:', len(d))\""
# 验证注册配置接口可用（web 200 已确认）
curl -s http://127.0.0.1:3077/api/register/config | head -c 200; echo
EOF
