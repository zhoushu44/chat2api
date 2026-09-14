#!/bin/bash
export SSHPASS='6Qz6ao0T1zvL'
sshpass -e ssh -o StrictHostKeyChecking=no -p 22 root@192.6.121.16 bash -s <<'EOF'
sleep 5
curl -s -o /dev/null -w "web: %{http_code}\n" http://127.0.0.1:3077/
docker exec chatgpt2api-11 sh -c "python3 -c \"import json; d=json.load(open('/data/accounts.json')); print('accounts:', len(d))\""
docker logs chatgpt2api-11 2>&1 | grep -iE 'error|panic' | head -5
echo "--- 日志尾部 ---"
docker logs chatgpt2api-11 2>&1 | tail -3
EOF
