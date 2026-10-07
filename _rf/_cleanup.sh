#!/bin/bash
echo "=== health check (local 3077) ==="
docker exec chatgpt2api-13 sh -c 'curl -s -m 5 http://127.0.0.1:3077/api/health' || echo "(health curl failed)"
echo
echo "=== cleanup temp test artifacts ==="
docker exec chatgpt2api-13 rm -f /tmp/oauth.test
rm -f /tmp/oauth.test /tmp/_run_recovery_test.sh /tmp/_deploy_binary.sh /tmp/_smoke_sentinel.sh \
      /tmp/_inspect_procs.sh /tmp/_logs.sh /tmp/_fetch_after.sh /tmp/chatgpt2api-go-new \
      /tmp/accounts.json /tmp/accounts_after.json
echo "kept backup:"; ls -la /root/chatgpt2api-go.bak-* 2>/dev/null | tail -3
echo "=== container status ==="
docker ps --filter name=chatgpt2api-13 --format '{{.Names}} | {{.Status}} | {{.Image}}'
