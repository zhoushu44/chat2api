import paramiko
import time

hostname = "192.6.121.16"
username = "root"
password = "6Qz6ao0T1zvL"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

print(f"连接到 {hostname}...")
client.connect(hostname, username=username, password=password, timeout=10)

def exec_cmd(cmd):
    print(f"\n执行：{cmd}")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=30)
    output = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    if output:
        print(output)
    if err:
        print("错误:", err)
    return output, err

# 检查 Docker 容器
exec_cmd("docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'")

# 检查 mihomo 配置
exec_cmd("docker exec mihomo cat /config.yaml 2>/dev/null || echo 'mihomo 容器不存在'")

# 测试代理
exec_cmd("curl -x socks5h://127.0.0.1:7890 -sS --connect-timeout 5 --max-time 10 http://ip-api.com/json 2>/dev/null || echo '代理测试失败'")

client.close()
print("\n连接已关闭")
