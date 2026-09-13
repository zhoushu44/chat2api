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
print("步骤 1: 检查 Docker 网络")
print("=" * 60)
exec_cmd("docker network ls")

print("\n" + "=" * 60)
print("步骤 2: 检查 mihomo 监听地址")
print("=" * 60)
exec_cmd("docker exec mihomo netstat -tlnp | grep 7890")

print("\n" + "=" * 60)
print("步骤 3: 从宿主机测试 mihomo 代理")
print("=" * 60)
exec_cmd("curl -x socks5h://127.0.0.1:7890 -sS --connect-timeout 5 --max-time 10 http://ip-api.com/json")

print("\n" + "=" * 60)
print("步骤 4: 获取宿主机网关地址")
print("=" * 60)
exec_cmd("ip route | grep default")

print("\n" + "=" * 60)
print("步骤 5: 从 FlareSolverr 容器测试宿主机网关")
print("=" * 60)
exec_cmd("docker exec flaresolverr curl -x socks5h://host.docker.internal:7890 -sS --connect-timeout 5 --max-time 10 http://ip-api.com/json || echo '需要配置 extra_hosts'")

print("\n" + "=" * 60)
print("步骤 6: 重启 FlareSolverr 并添加宿主机网关配置")
print("=" * 60)
exec_cmd("docker rm -f flaresolverr")
exec_cmd("""docker run -d \\
  --name flaresolverr \\
  --restart always \\
  --add-host host.docker.internal:host-gateway \\
  -p 0.0.0.0:8191:8191 \\
  -e LOG_LEVEL=info \\
  -e HEADLESS=true \\
  ghcr.io/flaresolverr/flaresolverr:latest""")

print("\n" + "=" * 60)
print("步骤 7: 等待启动并测试代理连接")
print("=" * 60)
exec_cmd("sleep 8")
exec_cmd("""curl -X POST http://127.0.0.1:8191/v1 \\
  -H "Content-Type: application/json" \\
  -d '{
    "cmd":"request.get",
    "url":"https://www.google.com",
    "maxTimeout":60000,
    "proxy":{
      "url":"socks5://host.docker.internal:7890"
    }
  }'""", timeout=90)

client.close()
print("\n连接已关闭")
