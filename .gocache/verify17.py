import paramiko, json, time

c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('195.72.185.32', username='root', password='6Qz6ao0T1zvL', timeout=30)

# 1. 健康检查
_,o,_ = c.exec_command("curl -s -o /dev/null -w 'healthz: %{http_code}\\n' http://127.0.0.1:3077/healthz", timeout=30)
print(o.read().decode())

# 2. 勾选框功能验证：settings 接口读超分段（应有 compress 字段）
_,o,_ = c.exec_command("curl -s http://127.0.0.1:3077/api/settings -H 'Authorization: Bearer zs1236547'", timeout=30)
try:
    cfg = json.loads(o.read().decode())
    sr = (cfg.get('config') or {}).get('super_resolution') or {}
    print('seed 超分段:', json.dumps({k: v for k, v in sr.items() if k in ('enabled','compress','output_quality')}, ensure_ascii=False))
except Exception as ex:
    print('settings 读取失败:', ex)

# 3. 前端页面勾选框渲染验证（首页 HTML 引用新产物）
_,o,_ = c.exec_command("curl -s http://127.0.0.1:3077/ | grep -oE 'assets/index-[^\"]+\\.js' | head -1", timeout=30)
idx = o.read().decode().strip()
print('前端入口:', idx)
_,o,_ = c.exec_command("docker exec chatgpt2api-13 sh -c \"grep -l '压缩成品' /internal/api/web_dist/assets/Settings-*.js 2>/dev/null || grep -rl '压缩成品' /app/* 2>/dev/null | head -1\"", timeout=30)
print('勾选框文本所在产物:', o.read().decode().strip()[:100])

# 4. 勾选压缩（写 settings）→ 生图验证 JPEG
_,o,_ = c.exec_command("""curl -s -X POST http://127.0.0.1:3077/api/settings -H 'Authorization: Bearer zs1236547' -H 'Content-Type: application/json' -d '{\"super_resolution\":{\"enabled\":true,\"compress\":true,\"output_quality\":90}}'""", timeout=30)
try:
    r = json.loads(o.read().decode())
    print('保存 compress=true:', json.dumps(r.get('applied', []), ensure_ascii=False))
except Exception as ex:
    print('save err', ex)

# 5. 4K 生图验证（应出 JPEG URL）
_,o,_ = c.exec_command("timeout 500 curl -s -X POST http://127.0.0.1:3077/v1/images/generations -H 'Authorization: Bearer zs1236547' -H 'Content-Type: application/json' -d '{\"model\":\"gpt-image-2\",\"prompt\":\"a red vintage car on a coastal road\",\"size\":\"4k\",\"n\":1}' -o /tmp/v17.json -w 'gen4k: %{http_code} (%{time_total}s)\\n'", timeout=520)
print(o.read().decode())
_,o,_ = c.exec_command("docker cp /tmp/v17.json chatgpt2api-13:/tmp/v17.json && docker exec chatgpt2api-13 python3 -c \"import json; print('URL:', json.load(open('/tmp/v17.json'))['data'][0].get('url','无')[:100])\"", timeout=60)
url = o.read().decode().strip().replace('URL: ', '')
_,o,_ = c.exec_command("curl -sI --max-time 30 '" + url + "' | grep -iE 'content-length|content-type'", timeout=60)
print('成品:', o.read().decode())
_,o,_ = c.exec_command("docker logs chatgpt2api-13 --since 5m 2>&1 | grep superres | tail -1", timeout=30)
print('日志:', o.read().decode()[:300])
c.close()
