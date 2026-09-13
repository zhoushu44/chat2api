#!/usr/bin/env python3
import paramiko
import secrets
import base64

hostname = "192.6.121.16"
username = "root"
password = "6Qz6ao0T1zvL"

try:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname, username=username, password=password, timeout=10)
    
    # 生成必需的密钥
    jwt_secret = secrets.token_urlsafe(32)  # 至少 32 字符
    encryption_key = secrets.token_bytes(32)  # 32 字节
    encryption_key_b64 = base64.b64encode(encryption_key).decode('utf-8')
    
    print(f"[+] 生成 JWT 密钥：{jwt_secret[:20]}...")
    print(f"[+] 生成加密密钥 (Base64): {encryption_key_b64[:20]}...")
    
    # 停止旧容器
    print("[*] 停止并删除旧容器...")
    stdin, stdout, stderr = client.exec_command("docker stop grok2api 2>/dev/null; docker rm grok2api 2>/dev/null")
    stdout.read().decode('utf-8')
    
    # 创建完整的配置文件
    print("\n[*] 创建完整的配置文件...")
    config_content = f"""# grok2api 配置文件
# 参考：https://github.com/chenyme/grok2api

# 服务器配置
server:
  listen: "0.0.0.0:8000"

# 密钥配置（必需）
secrets:
  jwtSecret: "{jwt_secret}"
  credentialEncryptionKey: "{encryption_key_b64}"

# 可选：认证配置
# auth:
#   token: "your-token-here"

# 可选：Grok API 配置
# grok:
#   email: "your-email@example.com"
#   password: "your-password"
"""
    
    stdin, stdout, stderr = client.exec_command(f"cat > /root/grok_data/config.yaml << 'EOF'\n{config_content}\nEOF")
    error = stderr.read().decode('utf-8')
    
    if error.strip():
        print(f"[!] 创建配置文件失败：{error}")
    else:
        print("[✓] 配置文件已创建")
        
        # 启动新容器
        print("\n[*] 启动新容器...")
        run_cmd = """docker run -d \\
  --name grok2api \\
  --restart unless-stopped \\
  -p 0.0.0.0:8000:8000 \\
  -v /root/grok_data/config.yaml:/run/grok2api/config.yaml \\
  -e TZ=Asia/Shanghai \\
  ghcr.io/chenyme/grok2api:latest"""
        
        stdin, stdout, stderr = client.exec_command(run_cmd.replace("\\\n", " ").replace("\\", ""))
        output = stdout.read().decode('utf-8')
        error = stderr.read().decode('utf-8')
        
        if output.strip():
            container_id = output.strip()
            print(f"[✓] 容器已启动：{container_id[:12]}")
            
            # 等待容器启动
            import time
            print("\n[*] 等待容器启动...")
            time.sleep(10)
            
            # 检查容器状态
            print("\n[*] 检查容器状态...")
            stdin, stdout, stderr = client.exec_command("docker ps --filter name=grok2api --format 'table {{.ID}}\\t{{.Names}}\\t{{.Image}}\\t{{.Status}}\\t{{.Ports}}'")
            output = stdout.read().decode('utf-8')
            print(output)
            
            # 检查日志
            print("\n[*] 检查容器日志...")
            stdin, stdout, stderr = client.exec_command("docker logs grok2api --tail 20")
            logs = stdout.read().decode('utf-8')
            print(logs if logs else "日志为空")
            
            # 测试健康检查
            print("\n[*] 测试健康检查端点...")
            stdin, stdout, stderr = client.exec_command("sleep 3 && curl -s http://127.0.0.1:8000/healthz 2>&1")
            health = stdout.read().decode('utf-8')
            print(f"健康检查响应：{health if health else '无响应'}")
            
            # 最终状态检查
            print("\n[*] 最终状态检查...")
            stdin, stdout, stderr = client.exec_command("sleep 5 && docker ps --filter name=grok2api --format '{{.Status}}'")
            status = stdout.read().decode('utf-8').strip()
            
            if "Up" in status and "healthy" in status:
                print("\n[✓✓✓] 升级成功！grok2api 已运行最新版本。")
                print(f"容器 ID: {container_id[:12]}")
                print("访问地址：http://192.6.121.16:8000")
                print("配置文件：/root/grok_data/config.yaml")
            elif "Up" in status:
                print("\n[✓] 容器已启动，正在健康检查中...")
                print(f"容器 ID: {container_id[:12]}")
                print("访问地址：http://192.6.121.16:8000")
            else:
                print(f"\n[!] 容器状态：{status}")
                print("请检查日志以获取更多信息")
        else:
            print(f"[!] 启动失败：{error}")
    
    client.close()
    
except Exception as e:
    print(f"[!] 错误：{e}")
    import traceback
    traceback.print_exc()
