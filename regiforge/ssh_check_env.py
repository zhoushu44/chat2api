#!/usr/bin/env python3
import paramiko

hostname = "192.6.121.16"
username = "root"
password = "6Qz6ao0T1zvL"

try:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname, username=username, password=password, timeout=10)
    
    # 查看镜像的环境变量
    print("=== 查看镜像的环境变量 ===")
    stdin, stdout, stderr = client.exec_command("docker inspect ghcr.io/chenyme/grok2api:latest --format '{{json .Config.Env}}' | python3 -m json.tool 2>/dev/null || docker inspect ghcr.io/chenyme/grok2api:latest --format '{{json .Config.Env}}'")
    env = stdout.read().decode('utf-8')
    print(env)
    
    # 查看镜像的 CMD 和 ENTRYPOINT
    print("\n=== 查看镜像启动命令 ===")
    stdin, stdout, stderr = client.exec_command("docker inspect ghcr.io/chenyme/grok2api:latest --format '{{json .Config.Cmd}}' | python3 -m json.tool 2>/dev/null || docker inspect ghcr.io/chenyme/grok2api:latest --format '{{json .Config.Cmd}}'")
    cmd = stdout.read().decode('utf-8')
    print(cmd)
    
    stdin, stdout, stderr = client.exec_command("docker inspect ghcr.io/chenyme/grok2api:latest --format '{{json .Config.Entrypoint}}' | python3 -m json.tool 2>/dev/null || docker inspect ghcr.io/chenyme/grok2api:latest --format '{{json .Config.Entrypoint}}'")
    entrypoint = stdout.read().decode('utf-8')
    print(entrypoint)
    
    # 查看镜像的 ExposedPorts
    print("\n=== 查看镜像暴露端口 ===")
    stdin, stdout, stderr = client.exec_command("docker inspect ghcr.io/chenyme/grok2api:latest --format '{{json .Config.ExposedPorts}}' | python3 -m json.tool 2>/dev/null || docker inspect ghcr.io/chenyme/grok2api:latest --format '{{json .Config.ExposedPorts}}'")
    ports = stdout.read().decode('utf-8')
    print(ports)
    
    # 尝试无配置文件启动，使用环境变量
    print("\n=== 尝试无配置文件启动（使用环境变量） ===")
    stdin, stdout, stderr = client.exec_command("docker stop grok2api 2>/dev/null; docker rm grok2api 2>/dev/null")
    stdout.read().decode('utf-8')
    
    # 使用环境变量启动
    run_cmd = """docker run -d --name grok2api --restart unless-stopped -p 8000:8000 -e TZ=Asia/Shanghai -e GROK2API_ADMIN_USERNAME=admin -e GROK2API_ADMIN_PASSWORD=admin123456 ghcr.io/chenyme/grok2api:latest"""
    
    stdin, stdout, stderr = client.exec_command(run_cmd)
    output = stdout.read().decode('utf-8')
    error = stderr.read().decode('utf-8')
    
    if output.strip():
        container_id = output.strip()
        print(f"[✓] 容器已启动：{container_id[:12]}")
        
        import time
        time.sleep(10)
        
        print("\n=== 检查容器状态 ===")
        stdin, stdout, stderr = client.exec_command("docker ps --filter name=grok2api --format 'table {{.ID}}\\t{{.Names}}\\t{{.Image}}\\t{{.Status}}\\t{{.Ports}}'")
        print(stdout.read().decode('utf-8'))
        
        print("\n=== 检查容器日志 ===")
        stdin, stdout, stderr = client.exec_command("docker logs grok2api 2>&1 | tail -30")
        print(stdout.read().decode('utf-8'))
    else:
        print(f"[!] 启动失败：{error}")
    
    client.close()
    
except Exception as e:
    print(f"错误：{e}")
