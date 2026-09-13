import paramiko
import json
import re

hostname = "192.6.121.16"
username = "root"
password = "6Qz6ao0T1zvL"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname, username=username, password=password, timeout=10)

def exec_cmd(cmd, timeout=120):
    print(f"\n执行：{cmd}")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    output = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    if output:
        print(output)
    if err and len(err) > 10:
        print("错误:", err[:500])
    return output, err

print("=" * 80)
print("ChatGPT 注册 - FlareSolverr 详细测试")
print("=" * 80)

print("\n" + "=" * 80)
print("测试：访问 ChatGPT 登录页面（使用 mihomo 代理）并提取 Cookie")
print("=" * 80)
result = exec_cmd("""curl -s -X POST http://127.0.0.1:8191/v1 \\
  -H "Content-Type: application/json" \\
  -d '{
    "cmd":"request.get",
    "url":"https://auth.openai.com/authorize?client_id=3nVnEy6tI5iGqGZNv9VnN9",
    "maxTimeout":60000,
    "proxy":{
      "url":"socks5://host.docker.internal:7890"
    }
  }'""", timeout=90)

# 解析返回的 JSON
try:
    json_match = re.search(r'(\{.*\})', result[0], re.DOTALL)
    if json_match:
        data = json.loads(json_match.group(1))
        print("\n" + "=" * 80)
        print("解析结果")
        print("=" * 80)
        print(f"Status: {data.get('status', 'N/A')}")
        print(f"Message: {data.get('message', 'N/A')}")
        
        if 'solution' in data:
            solution = data['solution']
            print(f"\nHTTP 状态码：{solution.get('status', 'N/A')}")
            print(f"最终 URL: {solution.get('url', 'N/A')[:100]}")
            
            cookies = solution.get('cookies', [])
            print(f"\n✅ 成功获取 Cookie，数量：{len(cookies)}")
            if cookies:
                print("\nCookie 详情:")
                for c in cookies:
                    name = c.get('name', 'unknown')
                    value = c.get('value', '')
                    domain = c.get('domain', '')
                    print(f"  - {name}: {value[:80]}... (domain: {domain})")
            
            user_agent = solution.get('userAgent', '')
            if user_agent:
                print(f"\nUser-Agent:\n  {user_agent}")
            
            response = solution.get('response', '')
            if response:
                print(f"\n页面 HTML 长度：{len(response)} 字符")
                # 检查是否有 Cloudflare 相关特征
                if 'cf-' in response.lower() or 'cloudflare' in response.lower():
                    print("⚠️ 页面包含 Cloudflare 相关标记")
                else:
                    print("✅ 页面未检测到 Cloudflare 标记")
                
                # 检查是否有 OpenAI 相关特征
                if 'openai' in response.lower() or 'auth0' in response.lower():
                    print("✅ 页面包含 OpenAI/Auth0 相关标记")
except Exception as e:
    print(f"解析返回结果失败：{e}")
    print("\n原始返回（前 2000 字符）:")
    print(result[0][:2000])

print("\n" + "=" * 80)
print("查看 FlareSolverr 最近日志")
print("=" * 80)
exec_cmd("docker logs flaresolverr --tail 15")

client.close()
print("\n" + "=" * 80)
print("测试完成！")
print("=" * 80)
