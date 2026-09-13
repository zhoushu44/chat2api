"""测试: 直接调 api.ngc.nvidia.com/login 获取 NVGS login key。

抓包显示 OAuth 链起点是:
  GET api.ngc.nvidia.com/login?email=...&app=...&redirect_uri=...
  → 302 login.nvidia.com/authorize?...
  → 302 accounts.nvgs.nvidia.com/api/1/oauth/authorize?...
  → 302 login.nvgs.nvidia.com/v1/login?key=xxx

api.ngc.nvidia.com 无 CF,如果直接能获取 key,阶段 3 就能纯 HTTP。
"""
import sys
import re
import secrets
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode

root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root))

from curl_cffi import requests as cc_requests

PROXY = "socks5://sockstest:socks-pass%401@192.6.121.16:7890"
TEST_EMAIL = "test_probe_only@zhoushu.kdns.fr"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"


def try_login(app_value, redirect_uri):
    session = cc_requests.Session(impersonate="chrome145")
    session.proxies = {"http": PROXY, "https": PROXY}

    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "user-agent": UA,
    }

    params = {
        "email": TEST_EMAIL,
        "app": app_value,
        "redirect_uri": redirect_uri,
    }

    url = f"https://api.ngc.nvidia.com/login?{urlencode(params)}"
    print(f"\n--- app={app_value!r} redirect_uri={redirect_uri!r} ---")
    print(f"GET {url[:120]}")

    resp = session.get(url, headers=headers, allow_redirects=False, timeout=30)
    print(f"  HTTP {resp.status_code}")
    location = resp.headers.get("location", "")
    print(f"  Location: {location[:200]}")

    # 跟随重定向链
    current_url = location
    for hop in range(8):
        if not current_url:
            break
        # 检查当前 URL 是否含 key
        parsed = urlparse(current_url)
        q = parse_qs(parsed.query)
        if "key" in q and "error" not in parsed.query:
            key = q["key"][0]
            print(f"  ✅ hop {hop}: 提取到 key: {key[:40]}...")
            return key

        print(f"  [{hop+1}] GET {current_url[:120]}")
        resp = session.get(current_url, headers=headers, allow_redirects=False, timeout=30)
        print(f"      HTTP {resp.status_code}")
        location = resp.headers.get("location", "")
        if location:
            print(f"      → {location[:200]}")

        if resp.status_code not in (301, 302, 303, 307, 308):
            if "key=" in resp.text[:5000]:
                m = re.search(r'[?&]key=([a-zA-Z0-9._\-]+)', resp.text[:5000])
                if m:
                    print(f"  ✅ 从 HTML 提取 key: {m.group(1)[:40]}...")
                    return m.group(1)
            if "error" in current_url:
                parsed = urlparse(current_url)
                q = parse_qs(parsed.query)
                err = q.get("error_description", q.get("error_key", [""]))[0]
                print(f"  ❌ 错误: {err}")
            break
        current_url = location

    return None


def main():
    # 尝试多种 app + redirect_uri 组合
    combos = [
        ("build", "https://build.nvidia.com/"),
        ("ngc", "https://build.nvidia.com/"),
        ("playground", "https://build.nvidia.com/"),
        ("build", "https://api.ngc.nvidia.com/"),
        ("", "https://build.nvidia.com/"),
    ]

    for app, redir in combos:
        key = try_login(app, redir)
        if key:
            print(f"\n✅ 成功! app={app!r} redirect_uri={redir!r}")
            print(f"   key: {key[:60]}...")
            return key

    print("\n❌ 所有组合均未获取到 key")
    return None


if __name__ == "__main__":
    key = main()
    sys.exit(0 if key else 1)
