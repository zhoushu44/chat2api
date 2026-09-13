import paramiko
import json

hostname = "192.6.121.16"
username = "root"
password = "6Qz6ao0T1zvL"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname, username=username, password=password, timeout=10)

def exec_cmd(cmd, timeout=60):
    print(f"\n执行：{cmd}")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    output = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    if output:
        print(output)
    if err:
        print("错误:", err[:500])
    return output, err

print("=" * 80)
print("FlareSolverr + mihomo 完整测试（带密码/不带密码）")
print("=" * 80)

print("\n" + "=" * 80)
print("测试 1: 无代理访问 Google")
print("=" * 80)
exec_cmd("""curl -X POST http://127.0.0.1:8191/v1 \\
  -H "Content-Type: application/json" \\
  -d '{"cmd":"request.get","url":"https://www.google.com","maxTimeout":60000}' 2>&1 | head -5""", timeout=90)

print("\n" + "=" * 80)
print("测试 2: 使用 mihomo 代理（无认证）访问 Google")
print("=" * 80)
exec_cmd("""curl -X POST http://127.0.0.1:8191/v1 \\
  -H "Content-Type: application/json" \\
  -d '{
    "cmd":"request.get",
    "url":"https://www.google.com",
    "maxTimeout":60000,
    "proxy":{
      "url":"socks5://host.docker.internal:7890"
    }
  }' 2>&1 | head -5""", timeout=90)

print("\n" + "=" * 80)
print("测试 3: 使用 mihomo 代理访问 nowsecure.nl（Cloudflare 挑战）")
print("=" * 80)
exec_cmd("""curl -X POST http://127.0.0.1:8191/v1 \\
  -H "Content-Type: application/json" \\
  -d '{
    "cmd":"request.get",
    "url":"https://nowsecure.nl",
    "maxTimeout":60000,
    "proxy":{
      "url":"socks5://host.docker.internal:7890"
    }
  }' 2>&1 | head -10""", timeout=90)

print("\n" + "=" * 80)
print("测试 4: 检查返回的 Cookie")
print("=" * 80)
exec_cmd("""curl -X POST http://127.0.0.1:8191/v1 \\
  -H "Content-Type: application/json" \\
  -d '{
    "cmd":"request.get",
    "url":"https://nowsecure.nl",
    "maxTimeout":60000,
    "proxy":{
      "url":"socks5://host.docker.internal:7890"
    }
  }' 2>&1 | grep -o '"cookies":\\[[^]]*\\]' | head -1""", timeout=90)

print("\n" + "=" * 80)
print("测试 5: 检查返回的 User-Agent")
print("=" * 80)
exec_cmd("""curl -X POST http://127.0.0.1:8191/v1 \\
  -H "Content-Type: application/json" \\
  -d '{
    "cmd":"request.get",
    "url":"https://nowsecure.nl",
    "maxTimeout":60000,
    "proxy":{
      "url":"socks5://host.docker.internal:7890"
    }
  }' 2>&1 | grep -o '"userAgent":"[^"]*"' | head -1""", timeout=90)

print("\n" + "=" * 80)
print("测试 6: 查看 FlareSolverr 日志")
print("=" * 80)
exec_cmd("docker logs flaresolverr --tail 20")

client.close()
print("\n" + "=" * 80)
print("测试完成！")
print("=" * 80)
