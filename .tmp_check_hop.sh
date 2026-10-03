#!/bin/bash
set -u
echo "=== _oauth_get 定义与 hop_timeout ==="
docker exec regiforge grep -n "_oauth_get\|hop_timeout" /app/projects/chatgpt_register/steps/_http_engine.py | head -10
echo ""
docker exec regiforge sed -n '930,950p' /app/projects/chatgpt_register/steps/_http_engine.py
