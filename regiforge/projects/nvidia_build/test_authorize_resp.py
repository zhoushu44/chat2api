"""快速诊断：login.nvidia.com/authorize 返回的是纯重定向还是 HTML+JS？

如果返回 HTML（含 JS document.cookie），则 curl_cffi 无法获取 JS 设置的 cookie，
这能解释为什么 login.nvidia.com/callback/redirect 返回 server_error。
"""
import os
import sys
from urllib.parse import urlparse, parse_qs, urlencode
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

from curl_cffi import requests as cc_requests

PROXY_LINK = os.getenv("IPDEEP_DYNAMIC_LINK", "")
PROXY_ENCODED = PROXY_LINK.replace("socks5h://", "socks5://") if PROXY_LINK else ""
TEST_EMAIL = "test_probe@example.com"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)


def main():
    session = cc_requests.Session(impersonate="chrome145")
    if PROXY_ENCODED:
        session.proxies = {"http": PROXY_ENCODED, "https": PROXY_ENCODED}

    nav_headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "user-agent": UA,
        "referer": "https://build.nvidia.com/",
    }

    # 步骤 1: GET api.ngc.nvidia.com/login
    login_url = (
        "https://api.ngc.nvidia.com/login?"
        + urlencode({"email": TEST_EMAIL, "app": "api-catalog", "redirect_uri": "https://build.nvidia.com/"})
    )
    print(f"[1] GET {login_url[:90]}...")
    resp = session.get(login_url, headers=nav_headers, allow_redirects=False, timeout=30)
    print(f"    HTTP {resp.status_code}")
    loc = resp.headers.get("location", "")
    print(f"    Location: {loc[:120]}")
    # 打印 Set-Cookie
    set_cookies = resp.headers.get("set-cookie", "")
    if set_cookies:
        print(f"    Set-Cookie (前 200): {set_cookies[:200]}")

    # 步骤 2: 跟随到 login.nvidia.com/authorize
    hop = 0
    current_url = loc
    while current_url and hop < 8:
        hop += 1
        parsed = urlparse(current_url)
        print(f"\n[{hop+1}] GET {current_url[:120]}")
        resp = session.get(current_url, headers=nav_headers, allow_redirects=False, timeout=30)
        print(f"    HTTP {resp.status_code}")
        loc = resp.headers.get("location", "")
        print(f"    Location: {loc[:120] if loc else '(none)'}")

        # 检查是否是 HTML 响应（而非纯重定向）
        content_type = resp.headers.get("content-type", "")
        body = resp.text or ""
        if "html" in content_type.lower() or body.strip().startswith("<"):
            print(f"    Content-Type: {content_type}")
            print(f"    Body length: {len(body)}")
            # 检查是否有 document.cookie / JS cookie 设置
            if "document.cookie" in body:
                print("    ⚠️ 检测到 document.cookie —— JS 设置 cookie，curl_cffi 无法捕获！")
            if "<script" in body.lower():
                # 提取 script 片段
                import re
                scripts = re.findall(r"<script[^>]*>(.{0,300})", body[:5000], re.IGNORECASE | re.DOTALL)
                if scripts:
                    print(f"    Script 片段 (前 2 个): ")
                    for s in scripts[:2]:
                        print(f"      {s[:200]}")
            # 打印 body 前 500 字符
            print(f"    Body 前 500 字符:\n{body[:500]}")

        set_cookies = resp.headers.get("set-cookie", "")
        if set_cookies:
            print(f"    Set-Cookie: {set_cookies[:300]}")

        if resp.status_code not in (301, 302, 303, 307, 308) or not loc:
            print(f"    [停止] 非重定向或无 Location")
            break
        current_url = loc

    # 打印最终所有 cookies
    print("\n=== Session cookies ===")
    try:
        for c in session.cookies.jar:
            print(f"  {c.name} (domain={c.domain}, path={c.path}): {c.value[:40]}...")
    except Exception as e:
        print(f"  读 cookies 异常: {e}")
        print(f"  dict: {dict(session.cookies) if session.cookies else {}}")


if __name__ == "__main__":
    main()
