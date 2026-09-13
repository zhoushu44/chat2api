"""测试纯 HTTP 阶段 1：不走浏览器，直接用 curl_cffi 调 api.ngc.nvidia.com/login 获取 NVGS key。

目标：验证不携带任何 Bot Manager cookies 时，api.ngc.nvidia.com/login 是否可直达。
如果可以 → 阶段 1 可纯 HTTP，连 FlareSolverr 都不需要。
如果被拦 → 需要 FlareSolverr 先过 build.nvidia.com 拿 Bot Manager cookies。
"""
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))

from curl_cffi import requests as cc_requests

# 代理（socks5 直连，不走 forwarder）
PROXY = "socks5://sockstest:socks-pass@1@192.6.121.16:7890"
# 注意：curl_cffi 的 socks5 代理格式，密码含 @ 需要处理
# 实际使用时可能需要 URL 编码
PROXY_ENCODED = "socks5://sockstest:socks-pass%401@192.6.121.16:7890"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"

TEST_EMAIL = f"testhttp{int(time.time()) % 100000}@test.example.com"


def test_direct_no_cookies():
    """测试 1: 不带任何 cookies，直接调 api.ngc.nvidia.com/login"""
    print("\n" + "=" * 60)
    print("测试 1: 无 cookies 直调 api.ngc.nvidia.com/login")
    print("=" * 60)

    session = cc_requests.Session(impersonate="chrome145")
    session.proxies = {"http": PROXY_ENCODED, "https": PROXY_ENCODED}

    login_url = (
        f"https://api.ngc.nvidia.com/login?"
        + urlencode({
            "email": TEST_EMAIL,
            "app": "api-catalog",
            "redirect_uri": "https://build.nvidia.com/",
        })
    )

    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "user-agent": UA,
        "referer": "https://build.nvidia.com/",
    }

    print(f"GET {login_url[:80]}...")
    print(f"email: {TEST_EMAIL}")

    try:
        resp = session.get(login_url, headers=headers, allow_redirects=False, timeout=30)
        print(f"\n[hop 0] HTTP {resp.status_code}")
        print(f"  Location: {resp.headers.get('location', '(none)')[:120]}")
        print(f"  Server: {resp.headers.get('server', '(none)')}")

        # 手动跟随重定向链
        current_url = resp.headers.get("location", "")
        hop = 0
        key = None
        while current_url and hop < 10:
            hop += 1
            if not current_url.startswith("http"):
                # 相对 URL
                current_url = f"https://api.ngc.nvidia.com{current_url}"

            # 检查是否到了 NVGS login 页（含 key）
            parsed = urlparse(current_url)
            params = parse_qs(parsed.query)
            if "key" in params:
                key = params["key"][0]
                print(f"\n[hop {hop}] ✅ 到达 NVGS login，提取到 key!")
                print(f"  URL: {current_url[:120]}")
                print(f"  key: {key[:50]}...")
                break

            print(f"\n[hop {hop}] GET {current_url[:120]}")
            try:
                resp2 = session.get(current_url, headers=headers, allow_redirects=False, timeout=30)
                print(f"  HTTP {resp2.status_code}")
                loc = resp2.headers.get("location", "")
                print(f"  Location: {loc[:120]}")
                if resp2.status_code in (403, 503):
                    body_snippet = resp2.text[:300].lower()
                    if "just a moment" in body_snippet or "challenge" in body_snippet:
                        print("  ⚠️ 检测到 CF/Bot Manager 拦截！")
                    else:
                        print(f"  body: {resp2.text[:200]}")
                current_url = loc
            except Exception as e:
                print(f"  ❌ 异常: {e}")
                break

        if key:
            print(f"\n{'=' * 60}")
            print(f"✅ 成功！纯 HTTP 拿到 NVGS key（无 cookies，无浏览器）")
            print(f"   key 前 50 字符: {key[:50]}")
            return True
        else:
            print(f"\n❌ 未拿到 key（{hop} 跳后终止）")
            return False

    except Exception as e:
        print(f"❌ 异常: {e}")
        return False


def test_with_flaresolverr_cookies():
    """测试 2: 先用 FlareSolverr 过 build.nvidia.com 拿 Bot Manager cookies，再调 api.ngc.nvidia.com/login"""
    import asyncio
    import json
    from captcha.cloudflare.flaresolverr.provider import FlareSolverrProvider

    print("\n" + "=" * 60)
    print("测试 2: FlareSolverr 过 CF → 拿 cookies → 调 api.ngc.nvidia.com/login")
    print("=" * 60)

    async def get_cookies():
        provider = FlareSolverrProvider()
        provider.configure({
            "api_url": "http://192.6.121.16:8191/v1",
            "max_timeout": 60000,
        })
        result = await provider.solve(page_url="https://build.nvidia.com/?modal=signin")
        if not result:
            return None
        return json.loads(result)

    data = asyncio.run(get_cookies())
    if not data:
        print("❌ FlareSolverr 返回 None")
        return False

    cookies_list = data.get("cookies", [])
    ua = data.get("ua", UA)
    print(f"FlareSolverr 拿到 {len(cookies_list)} 个 cookies")
    print(f"UA: {ua[:60]}")

    # 构建 cookie dict
    cookie_dict = {}
    for c in cookies_list:
        if isinstance(c, dict) and c.get("name"):
            cookie_dict[c["name"]] = c.get("value", "")

    session = cc_requests.Session(impersonate="chrome145")
    session.proxies = {"http": PROXY_ENCODED, "https": PROXY_ENCODED}

    # 注入 cookies
    for name, value in cookie_dict.items():
        try:
            session.cookies.set(name, value, domain=".nvidia.com")
        except Exception:
            pass

    login_url = (
        f"https://api.ngc.nvidia.com/login?"
        + urlencode({
            "email": TEST_EMAIL,
            "app": "api-catalog",
            "redirect_uri": "https://build.nvidia.com/",
        })
    )

    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "user-agent": ua,  # 用 FlareSolverr 的 UA 保持一致
        "referer": "https://build.nvidia.com/",
    }

    print(f"\nGET {login_url[:80]}...")

    try:
        resp = session.get(login_url, headers=headers, allow_redirects=False, timeout=30)
        print(f"[hop 0] HTTP {resp.status_code}, Location: {resp.headers.get('location', '(none)')[:120]}")

        current_url = resp.headers.get("location", "")
        hop = 0
        key = None
        while current_url and hop < 10:
            hop += 1
            if not current_url.startswith("http"):
                current_url = f"https://api.ngc.nvidia.com{current_url}"

            parsed = urlparse(current_url)
            params = parse_qs(parsed.query)
            if "key" in params:
                key = params["key"][0]
                print(f"\n[hop {hop}] ✅ 到达 NVGS login，提取到 key!")
                print(f"  key: {key[:50]}...")
                break

            print(f"[hop {hop}] GET {current_url[:120]}")
            try:
                resp2 = session.get(current_url, headers=headers, allow_redirects=False, timeout=30)
                print(f"  HTTP {resp2.status_code}, Location: {resp2.headers.get('location', '(none)')[:120]}")
                current_url = resp2.headers.get("location", "")
            except Exception as e:
                print(f"  ❌ 异常: {e}")
                break

        if key:
            print(f"\n{'=' * 60}")
            print(f"✅ 成功！FlareSolverr + curl_cffi 拿到 NVGS key")
            return True
        else:
            print(f"\n❌ 未拿到 key")
            return False

    except Exception as e:
        print(f"❌ 异常: {e}")
        return False


if __name__ == "__main__":
    print(f"测试邮箱: {TEST_EMAIL}")
    print(f"代理: {PROXY_ENCODED}")

    # 先测试直调（无 cookies）
    ok1 = test_direct_no_cookies()

    if not ok1:
        print("\n直调失败，尝试 FlareSolverr 方案...")
        ok2 = test_with_flaresolverr_cookies()
        if ok2:
            print("\n💡 结论：需要 FlareSolverr 过 CF 拿 cookies 才能纯 HTTP 阶段 1")
        else:
            print("\n💡 结论：两种方案都失败，需进一步排查")
    else:
        print("\n💡 结论：api.ngc.nvidia.com/login 无需 Bot Manager cookies，可直接纯 HTTP")
