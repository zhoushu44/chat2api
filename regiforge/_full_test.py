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
        print("错误:", err)
    return output, err

print("=" * 80)
print("FlareSolverr + mihomo 完整测试报告")
print("=" * 80)

print("\n" + "=" * 80)
print("1. 检查容器状态")
print("=" * 80)
exec_cmd("docker ps | grep -E 'mihomo|flaresolverr'")

print("\n" + "=" * 80)
print("2. 测试 mihomo 当前代理出口（使用 cliproxy API）")
print("=" * 80)
result = exec_cmd("curl -x socks5h://127.0.0.1:7890 -sS --connect-timeout 5 --max-time 10 http://ip-api.com/json")
try:
    ip_info = json.loads(result[0].strip())
    print(f"出口 IP: {ip_info.get('query', 'N/A')}")
    print(f"国家：{ip_info.get('country', 'N/A')}")
    print(f"城市：{ip_info.get('city', 'N/A')}")
except:
    pass

print("\n" + "=" * 80)
print("3. 测试 FlareSolverr 无代理访问 Google")
print("=" * 80)
exec_cmd("""curl -X POST http://127.0.0.1:8191/v1 \\
  -H "Content-Type: application/json" \\
  -d '{"cmd":"request.get","url":"https://www.google.com","maxTimeout":60000}' | python3 -m json.tool | head -20""", timeout=90)

print("\n" + "=" * 80)
print("4. 测试 FlareSolverr + mihomo 代理访问 Google")
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
  }' | python3 -m json.tool | head -25""", timeout=90)

print("\n" + "=" * 80)
print("5. 测试 FlareSolverr + mihomo 访问 Cloudflare 保护网站")
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
  }' | python3 -m json.tool | head -30""", timeout=90)

print("\n" + "=" * 80)
print("6. 查看 FlareSolverr 最近日志")
print("=" * 80)
exec_cmd("docker logs flaresolverr --tail 15")

print("\n" + "=" * 80)
print("7. 验证 mihomo 配置")
print("=" * 80)
exec_cmd("docker exec mihomo cat /config.yaml")

client.close()
print("\n" + "=" * 80)
print("测试完成！")
print("=" * 80)
