#!/bin/bash
export SSHPASS='6Qz6ao0T1zvL'
sshpass -e ssh -o StrictHostKeyChecking=no -p 22 root@192.6.121.16 bash -s <<'EOF'
# /api/register 需要鉴权；403/401 都说明路由在、服务正常
curl -s -o /dev/null -w "register: %{http_code}\n" http://127.0.0.1:3077/api/register
EOF
