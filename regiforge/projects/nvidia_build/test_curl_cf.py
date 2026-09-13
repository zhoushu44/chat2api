"""快速验证：curl_cffi 走 socks5 代理直连 build.nvidia.com 能否过 CF。

如果服务器出口 IP 信誉好，curl_cffi 走代理应该能直接 HTTP 200，无需 FlareSolverr。
"""
import sys
from pathlib import Path
from curl_cffi import requests as cc_requests

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))

PROXY = "socks5://sockstest:socks-pass%401@192.6.121.16:7890"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"


def test():
    session = cc_requests.Session(impersonate="chrome145")
    session.proxies = {"http": PROXY, "https": PROXY}

    print(f"目标: https://build.nvidia.com/?modal=signin")
    print(f"代理: {PROXY}")
    print("=" * 60)

    # 测试 1: build.nvidia.com
    print("\n[1] GET build.nvidia.com/?modal=signin ...")
    try:
        resp = session.get(
            "https://build.nvidia.com/?modal=signin",
            headers={
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "accept-language": "en-US,en;q=0.9",
                "user-agent": UA,
            },
            allow_redirects=False,
            timeout=30,
        )
        print(f"  HTTP {resp.status_code}")
        print(f"  Location: {resp.headers.get('location', '(无)')[:80]}")
        print(f"  Server: {resp.headers.get('server', '(无)')}")
        print(f"  Body length: {len(resp.text)}")
        # CF 拦截特征
        body_lower = resp.text[:2000].lower()
        if "just a moment" in body_lower or "challenge" in body_lower or resp.status_code in (403, 503):
            print("  ⚠️  检测到 Cloudflare 挑战页")
        elif resp.status_code == 200:
            print("  ✅ 直接 200，无 CF 挑战")
        # 看 cookies
        cookie_names = [c.name for c in session.cookies.jar]
        print(f"  Cookies: {cookie_names}")
    except Exception as e:
        print(f"  ❌ 异常: {e}")

    # 测试 2: 直接走 NGC login（阶段3 入口，无 CF）
    print("\n[2] GET api.ngc.nvidia.com/login（阶段3入口，验证代理可达）...")
    try:
        from urllib.parse import urlencode
        url = "https://api.ngc.nvidia.com/login?" + urlencode({
            "email": "test@example.com",
            "app": "build",
            "redirect_uri": "https://build.nvidia.com/",
        })
        resp = session.get(
            url,
            headers={
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "user-agent": UA,
            },
            allow_redirects=False,
            timeout=30,
        )
        print(f"  HTTP {resp.status_code}")
        print(f"  Location: {resp.headers.get('location', '(无)')[:120]}")
    except Exception as e:
        print(f"  ❌ 异常: {e}")


if __name__ == "__main__":
    test()
