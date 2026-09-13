import paramiko

hostname = "192.6.121.16"
username = "root"
password = "6Qz6ao0T1zvL"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname, username=username, password=password, timeout=10)

def exec_cmd(cmd, timeout=30):
    print(f"\n{cmd}")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    output = stdout.read().decode('utf-8', errors='replace')
    if output:
        print(output)
    return output

print("=" * 80)
print("测试从 FlareSolverr 容器通过公网 IP 访问 mihomo")
print("=" * 80)

# 获取服务器公网 IP
exec_cmd("curl -s http://ip-api.com/json | grep -o '\"query\":\"[^\"]*\"' | cut -d'\"' -f4")

# 从 FlareSolverr 容器测试
print("\n从 FlareSolverr 容器通过公网 IP 测试：")
exec_cmd("docker exec flaresolverr curl -x socks5h://$(curl -s http://ip-api.com/json | grep -o '\"query\":\"[^\"]*\"' | cut -d'\"' -f4):7890 -sS --connect-timeout 5 http://ip-api.com/json 2>&1 || echo '测试失败'")

# 检查端口监听状态
print("\n检查 7890 端口监听状态：")
exec_cmd("netstat -tlnp | grep 7890 || ss -tlnp | grep 7890")

# 检查防火墙规则
print("\n检查防火墙状态：")
exec_cmd("ufw status 2>/dev/null | grep 7890 || echo 'UFW 未运行或无 7890 规则'")

client.close()
