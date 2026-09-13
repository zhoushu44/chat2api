#!/usr/bin/env python3
import paramiko
import time

hostname = "192.6.121.16"
username = "root"
password = "6Qz6ao0T1zvL"

try:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    print(f"[+] 连接到 {hostname}...")
    client.connect(hostname, username=username, password=password, timeout=10)
    
    # 检查配置文件是否存在
    print("[*] 检查配置文件...")
    stdin, stdout, stderr = client.exec_command("ls -la /root/grok_data/config.yaml && cat /root/grok_data/config.yaml")
    output = stdout.read().decode('utf-8')
    print(output)
    
    # 检查容器挂载
    print("\n[*] 检查容器挂载信息...")
    stdin, stdout, stderr = client.exec_command("docker inspect grok2api --format '{{json .Mounts}}' | python3 -m json.tool 2>/dev/null || docker inspect grok2api --format '{{json .Mounts}}'")
    mounts = stdout.read().decode('utf-8')
    print(mounts)
    
    # 等待并检查日志
    print("\n[*] 等待 3 秒后检查日志...")
    time.sleep(3)
    
    print("\n[*] 查看容器日志...")
    stdin, stdout, stderr = client.exec_command("docker logs grok2api 2>&1 | tail -50")
    logs = stdout.read().decode('utf-8')
    print(logs if logs else "日志为空")
    
    # 检查容器退出原因
    print("\n[*] 检查容器退出状态...")
    stdin, stdout, stderr = client.exec_command("docker inspect grok2api --format '{{.State.ExitCode}}: {{.State.Error}}'")
    state = stdout.read().decode('utf-8')
    print(f"退出状态：{state}")
    
    # 尝试在容器内执行命令
    print("\n[*] 尝试在容器内查看文件...")
    stdin, stdout, stderr = client.exec_command("docker exec grok2api ls -la /run/grok2api/ 2>&1")
    ls_output = stdout.read().decode('utf-8')
    print(ls_output if ls_output else "无法执行")
    
    client.close()
    
except Exception as e:
    print(f"[!] 错误：{e}")
    import traceback
    traceback.print_exc()
