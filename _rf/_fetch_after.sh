#!/bin/bash
echo "=== fresh accounts.json ==="
docker cp chatgpt2api-13:/data/accounts.json /tmp/accounts_after.json
ls -la /tmp/accounts_after.json
sha256sum /tmp/accounts_after.json
echo "=== oauth.test still running? ==="
docker exec chatgpt2api-13 ps -ef | grep -E 'oauth.test' | grep -v grep || echo "oauth.test NOT running"
