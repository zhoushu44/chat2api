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
print("检查并启动 FlareSolverr 服务")
print("=" * 80)

# 1. 检查容器状态
print("\n1. 检查 FlareSolverr 容器")
exec_cmd("docker ps -a | grep flaresolverr")

# 2. 如果不存在则创建
print("\n2. 启动/重启 FlareSolverr")
exec_cmd("""docker rm -f flaresolverr 2>/dev/null; \
docker run -d \\
  --name flaresolverr \\
  --restart always \\
  -p 0.0.0.0:8191:8191 \\
  -e LOG_LEVEL=info \\
  -e HEADLESS=true \\
  ghcr.io/flaresolverr/flaresolverr:latest""")

# 3. 等待启动
print("\n3. 等待容器启动...")
exec_cmd("sleep 10 && docker ps | grep flaresolverr")

# 4. 测试 API
print("\n4. 测试 FlareSolverr API（无代理）")
exec_cmd("""curl -X POST http://127.0.0.1:8191/v1 \\
  -H "Content-Type: application/json" \\
  -d '{"cmd":"request.get","url":"https://www.google.com","maxTimeout":60000}' 2>&1 | head -5""", timeout=90)

# 5. 测试带代理
print("\n5. 测试 FlareSolverr + mihomo 代理")
exec_cmd("""curl -X POST http://127.0.0.1:8191/v1 \\
  -H "Content-Type: application/json" \\
  -d '{
    "cmd":"request.get",
    "url":"https://auth.openai.com/",
    "maxTimeout":60000,
    "proxy":{
      "url":"socks5://host.docker.internal:7890"
    }
  }' 2>&1 | head -10""", timeout=90)

# 6. 查看日志
print("\n6. 查看 FlareSolverr 日志")
exec_cmd("docker logs flaresolverr --tail 20")

client.close()
print("\n" + "=" * 80)
print("检查完成！")
print("=" * 80)
