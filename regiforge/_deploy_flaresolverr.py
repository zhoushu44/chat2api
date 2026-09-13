import paramiko

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

print("=" * 60)
print("步骤 1: 拉取 FlareSolverr 镜像")
print("=" * 60)
exec_cmd("docker pull ghcr.io/flaresolverr/flaresolverr:latest", timeout=120)

print("\n" + "=" * 60)
print("步骤 2: 运行 FlareSolverr 容器")
print("=" * 60)
exec_cmd("""docker run -d \\
  --name flaresolverr \\
  --restart always \\
  -p 0.0.0.0:8191:8191 \\
  -e LOG_LEVEL=info \\
  -e HEADLESS=true \\
  ghcr.io/flaresolverr/flaresolverr:latest""")

print("\n" + "=" * 60)
print("步骤 3: 等待容器启动并检查状态")
print("=" * 60)
exec_cmd("sleep 5 && docker ps | grep flaresolverr")

print("\n" + "=" * 60)
print("步骤 4: 测试 FlareSolverr API（无代理）")
print("=" * 60)
exec_cmd("""curl -X POST http://127.0.0.1:8191/v1 \\
  -H "Content-Type: application/json" \\
  -d '{"cmd":"request.get","url":"https://www.google.com","maxTimeout":60000}'""", timeout=90)

print("\n" + "=" * 60)
print("步骤 5: 测试 FlareSolverr + mihomo 代理")
print("=" * 60)
exec_cmd("""curl -X POST http://127.0.0.1:8191/v1 \\
  -H "Content-Type: application/json" \\
  -d '{
    "cmd":"request.get",
    "url":"https://www.google.com",
    "maxTimeout":60000,
    "proxy":{
      "url":"socks5://127.0.0.1:7890"
    }
  }'""", timeout=90)

print("\n" + "=" * 60)
print("步骤 6: 查看 FlareSolverr 日志")
print("=" * 60)
exec_cmd("docker logs flaresolverr --tail 20")

client.close()
print("\n连接已关闭")
