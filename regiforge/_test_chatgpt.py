import paramiko
import json

hostname = "192.6.121.16"
username = "root"
password = "6Qz6ao0T1zvL"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname, username=username, password=password, timeout=10)

def exec_cmd(cmd, timeout=120):
    print(f"\n执行：{cmd}")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    output = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    if output:
        print(output)
    if err and len(err) > 10:
        print("错误:", err[:1000])
    return output, err

print("=" * 80)
print("ChatGPT 注册项目 - FlareSolverr 过 Cloudflare 测试")
print("=" * 80)

print("\n" + "=" * 80)
print("测试 1: 访问 ChatGPT 登录页面（无代理）")
print("=" * 80)
exec_cmd("""curl -X POST http://127.0.0.1:8191/v1 \\
  -H "Content-Type: application/json" \\
  -d '{
    "cmd":"request.get",
    "url":"https://auth.openai.com/authorize?client_id=3nVnEy6tI5iGqGZNv9VnN9",
    "maxTimeout":60000
  }' 2>&1 | grep -E '"status"|"message"|"userAgent"' | head -5""", timeout=90)

print("\n" + "=" * 80)
print("测试 2: 访问 ChatGPT 登录页面（使用 mihomo 代理）")
print("=" * 80)
exec_cmd("""curl -X POST http://127.0.0.1:8191/v1 \\
  -H "Content-Type: application/json" \\
  -d '{
    "cmd":"request.get",
    "url":"https://auth.openai.com/authorize?client_id=3nVnEy6tI5iGqGZNv9VnN9",
    "maxTimeout":60000,
    "proxy":{
      "url":"socks5://host.docker.internal:7890"
    }
  }' 2>&1 | grep -E '"status"|"message"|"userAgent"' | head -5""", timeout=90)

print("\n" + "=" * 80)
print("测试 3: 检查返回的 Cookie（使用代理）")
print("=" * 80)
result = exec_cmd("""curl -X POST http://127.0.0.1:8191/v1 \\
  -H "Content-Type: application/json" \\
  -d '{
    "cmd":"request.get",
    "url":"https://auth.openai.com/authorize?client_id=3nVnEy6tI5iGqGZNv9VnN9",
    "maxTimeout":60000,
    "proxy":{
      "url":"socks5://host.docker.internal:7890"
    }
  }' 2>&1""", timeout=90)

# 解析返回的 JSON
try:
    # 提取 JSON 部分
    import re
    json_match = re.search(r'(\{.*\})', result[0], re.DOTALL)
    if json_match:
        data = json.loads(json_match.group(1))
        if data.get('status') == 'ok' and 'solution' in data:
            cookies = data['solution'].get('cookies', [])
            print(f"\n✅ 成功获取 Cookie，数量：{len(cookies)}")
            if cookies:
                print("\nCookie 列表:")
                for c in cookies[:5]:
                    print(f"  - {c.get('name', 'unknown')}: {c.get('value', '')[:50]}...")
            
            user_agent = data['solution'].get('userAgent', '')
            if user_agent:
                print(f"\nUser-Agent: {user_agent[:80]}...")
            
            status_code = data['solution'].get('status', 0)
            print(f"\nHTTP 状态码：{status_code}")
except Exception as e:
    print(f"解析返回结果失败：{e}")

print("\n" + "=" * 80)
print("测试 4: 访问 ChatGPT 主页（使用代理）")
print("=" * 80)
exec_cmd("""curl -X POST http://127.0.0.1:8191/v1 \\
  -H "Content-Type: application/json" \\
  -d '{
    "cmd":"request.get",
    "url":"https://chat.openai.com/",
    "maxTimeout":60000,
    "proxy":{
      "url":"socks5://host.docker.internal:7890"
    }
  }' 2>&1 | grep -E '"status"|"message"' | head -3""", timeout=90)

print("\n" + "=" * 80)
print("测试 5: 查看 FlareSolverr 日志")
print("=" * 80)
exec_cmd("docker logs flaresolverr --tail 30")

client.close()
print("\n" + "=" * 80)
print("测试完成！")
print("=" * 80)
