#!/bin/bash
# 在容器内冒烟测试 sentinel 脚本的 requirements action（不依赖 Go 代码）。
set -u
C=chatgpt2api-13
SCRIPT=/opt/regiforge/projects/chatgpt_register/steps/_openai_sentinel_quickjs.js
SDK=/opt/regiforge/projects/chatgpt_register/steps/sentinel_vm/sdk.js

cat > /tmp/_smoke_req.json <<'JSON'
{"action":"requirements","flow":"authorize_continue","device_id":"11111111-2222-3333-4444-555555555555","user_agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36","platform":"Win32","vendor":"Google Inc.","hardware_concurrency":8,"language":"en-US","languages":["en-US","en"],"screen_width":1920,"screen_height":1080,"timezone":"UTC"}
JSON

docker cp /tmp/_smoke_req.json "$C:/tmp/_smoke_req.json"
echo "=== requirements action ==="
docker exec "$C" sh -lc "OPENAI_SENTINEL_SDK_FILE=$SDK node $SCRIPT < /tmp/_smoke_req.json"
echo ""
echo "=== exit=$? ==="
docker exec "$C" rm -f /tmp/_smoke_req.json
rm -f /tmp/_smoke_req.json
