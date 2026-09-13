"""NVIDIA HTTP 模式 - 使用 CaptchaRun CloudFlare5s 处理 Cloudflare

流程：
1. 调用 CaptchaRun CloudFlare5s 获取 cf_clearance + UA
2. 用 cf_clearance Cookie 访问 build.nvidia.com 获取 key
3. 用 key + Cookie 访问 NVGS 完成注册
"""
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))

from captcha.cloudflare.captcharun.provider import CaptchaRunCloudflareProvider
from curl_cffi import requests as cc_requests


async def test_captcharun_cf_nvidia():
    """测试使用 CaptchaRun CloudFlare5s 访问 build.nvidia.com"""
    print("=" * 60)
    print("NVIDIA - CaptchaRun CloudFlare5s 测试")
    print("=" * 60)
    
    # 加载配置
    config_path = root_dir / "data" / "config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    
    # 创建 CaptchaRun CloudFlare5s Provider
    provider = CaptchaRunCloudflareProvider()
    cf_config = config.get("captcha", {}).get("cloudflare", {}).get("captcharun", {})
    provider.configure(cf_config)
    
    # 代理信息
    proxy_server = "socks5://sockstest:socks-pass%401@192.6.121.16:7890"
    parsed = urlparse(proxy_server)
    proxy_host = parsed.hostname or ""
    proxy_port = parsed.port or 0
    proxy_login = parsed.username or ""
    proxy_password = parsed.password or ""
    
    print(f"\n🌐 目标 URL: https://build.nvidia.com/?modal=signin")
    print(f"🔧 CaptchaRun API: {cf_config.get('api_url')}")
    print(f"📡 代理：{proxy_host}:{proxy_port} (user={proxy_login})")
    print("=" * 60)
    
    try:
        # 步骤 1: 调用 CaptchaRun 获取 cf_clearance
        print("\n[步骤 1] 调用 CaptchaRun CloudFlare5s...")
        result_json = await provider.solve(
            sitekey="",
            page_url="https://build.nvidia.com/?modal=signin",
            proxy_host=proxy_host,
            proxy_port=proxy_port,
            proxy_login=proxy_login,
            proxy_password=proxy_password,
        )
        
        if not result_json:
            print("❌ CaptchaRun 未返回结果")
            return False
        
        data = json.loads(result_json)
        cf_clearance = data.get("cf_clearance", "")
        ua = data.get("ua", "")
        
        print(f"\n✅ CaptchaRun 成功！")
        print(f"  - cf_clearance: {cf_clearance[:40]}...")
        print(f"  - User-Agent: {ua[:50]}...")
        
        if not cf_clearance:
            print("❌ 未获取到 cf_clearance")
            return False
        
        # 步骤 2: 用 cf_clearance 访问 build.nvidia.com 获取 key
        print("\n[步骤 2] 用 cf_clearance 访问 build.nvidia.com...")
        
        session = cc_requests.Session(impersonate="chrome145")
        session.proxies = {"http": proxy_server, "https": proxy_server}
        
        # 设置 cf_clearance Cookie
        session.cookies.set("cf_clearance", cf_clearance, domain=".nvidia.com")
        
        # 设置 UA
        headers = {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "accept-language": "en-US,en;q=0.9",
            "user-agent": ua,
        }
        
        response = session.get(
            "https://build.nvidia.com/?modal=signin",
            headers=headers,
            allow_redirects=True,
            timeout=30,
        )
        
        status = response.status_code
        html = response.text
        
        print(f"  - HTTP {status}")
        print(f"  - HTML 长度: {len(html)}")
        
        if status == 200:
            print("\n✅ 成功访问 build.nvidia.com！")
            
            # 提取 key
            import re
            key = None
            patterns = [
                r'"key"\s*:\s*"([a-f0-9-]+)"',
                r'key\s*:\s*"([a-f0-9-]+)"',
                r'<meta[^>]+name=["\']?key["\']?[^>]+content=["\']([^"\']+)["\']',
                r'data-key=["\']([^"\']+)["\']',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, html, re.IGNORECASE)
                if match:
                    key = match.group(1)
                    print(f"\n✅ 提取到 key: {key[:20]}...")
                    break
            
            if not key:
                print("\n⚠️  未找到 key 参数")
                # 保存 HTML 供分析
                output_file = root_dir / "data" / "debug" / "nvidia_build_build_page.html"
                output_file.parent.mkdir(parents=True, exist_ok=True)
                with open(output_file, "w", encoding="utf-8") as f:
                    f.write(html)
                print(f"💾 HTML 已保存到：{output_file}")
                print("💡 可以查看 HTML 找到 key 的位置")
            else:
                # 步骤 3: 用 key 访问 NVGS
                print(f"\n[步骤 3] 用 key 访问 NVGS...")
                redirect_url = f"https://login.nvidia.com/v1/create-account?key={key}"
                
                response = session.get(
                    redirect_url,
                    headers=headers,
                    allow_redirects=True,
                    timeout=30,
                )
                
                status = response.status_code
                html = response.text
                
                print(f"  - HTTP {status}")
                print(f"  - HTML 长度: {len(html)}")
                
                if status == 200:
                    print("\n✅ 成功访问 NVGS！")
                    print("💡 后续可以提交注册表单")
                    return True
                else:
                    print(f"\n❌ NVGS 返回 HTTP {status}")
                    return False
        else:
            print(f"\n❌ build.nvidia.com 返回 HTTP {status}")
            return False
        
    except Exception as e:
        print(f"\n❌ 异常：{e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(test_captcharun_cf_nvidia())
    sys.exit(0 if success else 1)
