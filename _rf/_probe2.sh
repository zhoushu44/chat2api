#!/bin/bash
echo "=== host->container path check ==="
docker exec regiforge sh -lc 'ls /app/projects/chatgpt_register/steps/_sentinel_quickjs.py /app/projects/chatgpt_register/steps/_openai_sentinel_quickjs.js'
echo "=== flow strings inside sdk.js ==="
docker exec regiforge sh -lc 'grep -ohE "authorize_continue|username_password_[a-z_]+|oauth_[a-z_]+|email_otp[a-z_]*|\"so\"" /tmp/openai-sentinel-demo/20260219f9f6/sdk.js | sort -u'
echo "=== flow strings inside quickjs js ==="
docker exec regiforge sh -lc 'grep -ohE "authorize_continue|username_password_[a-z_]+|oauth_[a-z_]+|email_otp[a-z_]*" /app/projects/chatgpt_register/steps/_openai_sentinel_quickjs.js | sort -u'
echo "=== direct egress test (regiforge, 20s) ==="
docker exec regiforge sh -lc 'curl -s -o /dev/null -w "direct chatgpt csrf: %{http_code} in %{time_total}s\n" --max-time 20 https://chatgpt.com/api/auth/csrf'
echo "=== proxy egress test via socks5 mihomo ==="
docker exec regiforge sh -lc 'curl -s -o /dev/null -w "socks5 chatgpt csrf: %{http_code} in %{time_total}s\n" --max-time 25 --socks5-hostname "sockstest:socks-pass%401@195.72.185.32:7890" https://chatgpt.com/api/auth/csrf'
