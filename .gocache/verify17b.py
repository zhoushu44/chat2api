import paramiko, json

c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('195.72.185.32', username='root', password='6Qz6ao0T1zvL', timeout=30)
# 上一步 URL 提取失败（输出被 URL: 前缀污染）。直接从日志取 jpeg URL 并 HEAD
_,o,_ = c.exec_command("docker logs chatgpt2api-13 --since 6m 2>&1 | grep -oE 'https://[^ ]+\\.jpeg' | tail -1", timeout=30)
url = o.read().decode().strip()
print('URL:', url[:110])
_,o,_ = c.exec_command("curl -sI --max-time 30 '" + url + "' | grep -iE 'content-length|content-type'", timeout=60)
print('成品头:', o.read().decode())
# seed 里 super_resolution 为空的复核（data 卷里已有 settings.json，读它）
_,o,_ = c.exec_command("docker exec chatgpt2api-13 python3 -c \"import json; s=json.load(open('/data/settings.json')); sr=s.get('super_resolution',{}); print('settings.json 超分段:', json.dumps({k:sr.get(k) for k in ('enabled','compress','output_quality')}, ensure_ascii=False))\"", timeout=30)
print(o.read().decode()[:200])
c.close()
