#!/bin/bash
# 轮询 GitHub Action 构建状态，直到完成或超时
REPO=zhoushu44/chat2api
for i in $(seq 1 60); do
  resp=$(curl -s "https://api.github.com/repos/$REPO/actions/runs?per_page=1")
  status=$(echo "$resp" | python3 -c "import json,sys; d=json.load(sys.stdin); r=d['workflow_runs'][0]; print(r['status'], r['conclusion'], r['head_sha'][:7])")
  echo "[$i] $status"
  sha=$(echo "$status" | awk '{print $3}')
  st=$(echo "$status" | awk '{print $1}')
  if [ "$sha" = "3807345" ] && [ "$st" = "completed" ]; then
    echo "BUILD DONE: $status"
    exit 0
  fi
  sleep 30
done
echo "TIMEOUT"
exit 1
