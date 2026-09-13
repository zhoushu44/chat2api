"""测试: 直接调用 NVGS oauth/authorize 获取 login key(不经过 build.nvidia.com)。

accounts.nvgs.nvidia.com 无 CF 保护,如果能直接发起 OAuth 获取 key,
就能完全跳过浏览器,实现纯 HTTP 阶段 3。
"""
import sys
import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs

root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root))

from curl_cffi import requests as cc_requests

API_BASE = "https://accounts.nvgs.nvidia.com"
CLIENT_ID = "1214762014100529152"
PROXY = "socks5://sockstest:socks-pass%401@192.6.121.16:7890"
TEST_EMAIL = "test_probe_only@zhoushu.kdns.fr"


def main():
    session = cc_requests.Session(impersonate="chrome145")
    session.proxies = {"http": PROXY, "https": PROXY}

    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    }

    # 尝试直接调 oauth/authorize(不自动跟随重定向,逐跳检查)
    # 参数来自抓包: redirect_uri, client_id, state, response_type, scope, login_hint
    import secrets
    state = secrets.token_urlsafe(24)

    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": "https://build.nvidia.com/",
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "login_hint": TEST_EMAIL,
    }

    print(f"[1] GET {API_BASE}/api/1/oauth/authorize ...")
    print(f"    params: {list(params.keys())}")
    resp = session.get(
        f"{API_BASE}/api/1/oauth/authorize",
        params=params,
        headers=headers,
        allow_redirects=False,
        timeout=30,
    )
    print(f"    HTTP {resp.status_code}")
    print(f"    Location: {resp.headers.get('location', '')[:200]}")

    # 跟随重定向链(手动,最多 10 跳)
    current_url = resp.headers.get("location", "")
    for hop in range(10):
        if not current_url:
            print(f"    [跳 {hop+1}] 无 Location,停止")
            break
        print(f"\n[{hop+2}] GET {current_url[:150]} ...")
        resp = session.get(current_url, headers=headers, allow_redirects=False, timeout=30)
        print(f"    HTTP {resp.status_code}")
        location = resp.headers.get("location", "")
        print(f"    Location: {location[:200]}")

        # 检查最终 URL 是否含 key
        parsed = urlparse(current_url)
        q = parse_qs(parsed.query)
        if "key" in q:
            key = q["key"][0]
            print(f"\n✅ 提取到 key: {key[:40]}...")
            print(f"   最终 URL: {current_url[:120]}")
            return key

        if resp.status_code not in (301, 302, 303, 307, 308):
            # 不是重定向,检查 HTML 中是否有 key
            if "key=" in resp.text[:5000]:
                import re
                m = re.search(r'key=([a-zA-Z0-9._\-]+)', resp.text[:5000])
                if m:
                    print(f"\n✅ 从 HTML 提取到 key: {m.group(1)[:40]}...")
                    return m.group(1)
            print(f"    [跳 {hop+1}] 非重定向(HTTP {resp.status_code}),停止")
            print(f"    Body 前 300 字: {resp.text[:300]}")
            break
        current_url = location

    print("\n❌ 未能从 OAuth 重定向链提取到 key")
    return None


if __name__ == "__main__":
    key = main()
    sys.exit(0 if key else 1)
