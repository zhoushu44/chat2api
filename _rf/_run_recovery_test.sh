#!/bin/bash
# 在容器内跑真实协议登录测试（真 sentinel），验证 password/verify 是否 200
set -e
CRED='ad188902@outlook.com:nO8mjMl59q!A1:DGFNTSU6KDEWKMCG7SRUPZJRHD36HD3H'
echo "=== copy test binary into container ==="
docker cp /tmp/oauth.test chatgpt2api-13:/tmp/oauth.test
docker exec chatgpt2api-13 chmod +x /tmp/oauth.test
echo "=== run real recovery login test ==="
docker exec -e CHAT2API_RECOVERY_TEST="$CRED" chatgpt2api-13 /tmp/oauth.test -test.run TestRecoveryLoginReal -test.v 2>&1 | tail -120
echo "=== exit=$? ==="
