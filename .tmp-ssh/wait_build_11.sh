#!/bin/bash
REPO=zhoushu44/chat2api
for i in $(seq 1 40); do
  resp=$(curl -s "https://api.github.com/repos/$REPO/actions/runs?per_page=1")
  echo "$resp" | python3 -c "import json,sys; d=json.load(sys.stdin); r=d['workflow_runs'][0]; print('run:', r['head_sha'][:7], r['status'], r['conclusion'])"
  st=$(echo "$resp" | python3 -c "import json,sys; d=json.load(sys.stdin); r=d['workflow_runs'][0]; print(r['status'], r['conclusion'])")
  if echo "$st" | grep -q "^completed"; then exit 0; fi
  sleep 30
done
echo TIMEOUT; exit 1
