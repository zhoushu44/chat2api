#!/bin/bash
echo "=== recent scheduler/recovery/sentinel logs ==="
docker logs --since 10m chatgpt2api-13 2>&1 | grep -E '\[Scheduler\]|\[recovery\]|sentinel|401|恢复' | tail -80
echo
echo "=== last 25 lines ==="
docker logs --tail 25 chatgpt2api-13 2>&1
