#!/bin/bash
echo "=== containers ==="
docker ps --format '{{.Names}} {{.Image}}'
echo "=== node/python/curl in regiforge ==="
docker exec regiforge sh -lc 'which node; which python3; which python; which curl; node -v 2>/dev/null; python3 -V 2>/dev/null'
echo "=== curl_cffi version ==="
docker exec regiforge sh -lc 'python3 -c "import curl_cffi, sys; print(curl_cffi.__version__)"'
echo "=== flow names in regiforge steps ==="
grep -rhoE '(authorize_continue|username_password_[a-z]+|oauth_[a-z_]+|email_otp[a-z_]*|"so")' /opt/regiforge/app/projects/chatgpt_register/steps/ 2>/dev/null | sort -u
echo "=== sentinel sdk cache ==="
docker exec regiforge sh -lc 'ls -la /tmp/openai-sentinel-demo/*/ 2>/dev/null; find /tmp -iname "sdk.js" 2>/dev/null | head'
echo "=== proxy listen ==="
netstat -lntp 2>/dev/null | grep -E '7890|7892|4433|8445' || ss -lntp | grep -E '7890|7892|4433|8445'
