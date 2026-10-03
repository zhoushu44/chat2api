#!/bin/bash
# 修复「注册全部失败」：删除 regiforge 容器内 wary provider 的 MARKER 测试代码并重启
# 背景：10-02 晚排查时插入的标记代码 `or True` 无条件抛异常，留在容器内未删，
#       10-03 10:54 的注册任务 2fa8b0a66d8c 20/20 全部失败：MARKER-TEST-CODE-LOADED
# 用法：SSH 上服务器后 bash 本脚本（或逐条执行）
set -u

echo "=== 1. 备份当前文件 ==="
docker exec regiforge sh -c "mkdir -p /tmp/bak-20261003 && cp /app/proxy/wary/provider.py /tmp/bak-20261003/provider.py.bak"
echo "BACKUP_OK"

echo ""
echo "=== 2. 确认 marker 代码还在 ==="
docker exec regiforge grep -n "MARKER-TEST-CODE-LOADED" /app/proxy/wary/provider.py || echo "(marker 不在了？请人工检查)"

echo ""
echo "=== 3. 生成删除脚本并执行（精确匹配 if 块三行） ==="
cat > /tmp/rm_marker.py << 'PYEOF'
path = '/app/proxy/wary/provider.py'
src = open(path, encoding='utf-8').read()
bad = '''        import os as _os
        if _os.environ.get("WARY_MARKER_TEST") or True:  # TODO: 临时标记测试，验证后删除
            raise RuntimeError("MARKER-TEST-CODE-LOADED")
'''
if bad in src:
    open(path, 'w', encoding='utf-8').write(src.replace(bad, ''))
    print('MARKER_REMOVED')
else:
    print('MARKER_PATTERN_NOT_FOUND（可能已删或缩进不同，人工核对）')
PYEOF
docker cp /tmp/rm_marker.py regiforge:/tmp/rm_marker.py
docker exec regiforge python3 /tmp/rm_marker.py

echo ""
echo "=== 4. 语法检查 + 清 pycache ==="
docker exec regiforge python3 -c "import ast; ast.parse(open('/app/proxy/wary/provider.py', encoding='utf-8').read()); print('SYNTAX_OK')"
docker exec regiforge sh -c "find /app -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null; true"
if docker exec regiforge grep -c "MARKER-TEST-CODE-LOADED" /app/proxy/wary/provider.py; then
  echo "!! marker 仍在，中止"; exit 1
else
  echo "MARKER_COUNT_0"
fi

echo ""
echo "=== 5. 重启 regiforge（uvicorn 不重启旧代码仍在内存） ==="
docker restart regiforge
sleep 22
docker ps --filter name=regiforge --format '{{.Status}}'

echo ""
echo "=== 6. 健康 ==="
curl -s --max-time 8 "http://127.0.0.1:8787/api/meta" | head -c 100
echo ""

echo "=== 7. 起验证任务（3 号，并发 1） ==="
TASK=$(curl -s --max-time 15 -X POST "http://127.0.0.1:8787/api/tasks" -H "Content-Type: application/json" -d '{
  "project_id": "chatgpt_register",
  "total": 3,
  "concurrency": 1,
  "headless": true,
  "captcha_id": "turnstile.browser_manual",
  "email_id": "mailnest",
  "proxy_id": "wary",
  "export_id": "chatgpt2api"
}')
TASK_ID=$(echo "$TASK" | grep -oE '"task_id":"[a-f0-9]+"' | cut -d'"' -f4)
echo "task_id: $TASK_ID"
echo "$TASK_ID" > /tmp/verify_task_id.txt

echo ""
echo "=== 8. 等 90s 看日志（确认无 MARKER，观察失败类型） ==="
sleep 90
curl -s --max-time 10 "http://127.0.0.1:8787/api/tasks/$TASK_ID/logs" | python3 -c "
import json, sys
d = json.load(sys.stdin)
for line in d.get('lines', [])[-30:]:
    print(line)
" 2>/dev/null | grep -vE 'DEBUG account'

echo ""
echo "=== 回滚 ==="
echo "docker exec regiforge sh -c 'cat /tmp/bak-20261003/provider.py.bak > /app/proxy/wary/provider.py' && docker restart regiforge"