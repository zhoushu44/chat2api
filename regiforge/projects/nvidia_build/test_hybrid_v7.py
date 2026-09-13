"""NVIDIA 混合模式 v7 - 正确的 validation 格式

validation.response = hCaptcha token
"""
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))


async def test_hybrid_v7():
    """混合模式 v7 - validation.response = hCaptcha token"""
    print("=" * 60)
    print("NVIDIA 混合模式 v7 - validation.response = hCaptcha")
    print("=" * 60)

    from patchright.async_api import async_playwright
    from curl_cffi import requests as cc_requests
    import random

    test_email = f"{''.join(str(random.randint(0, 9)) for _ in range(8))}@zhoushu.kdns.fr"
    test_password = "zs1236547."
    proxy_server = "http://127.0.0.1:7897"
    HCAPTCHA_SITEKEY = "3443d8f6-da7a-4326-929f-4d7fc89ab0d1"
    API_BASE = "https://accounts.nvgs.nvidia.com"

    print(f"\n📧 邮箱: {test_email}")
    print("=" * 60)

    # 阶段 1: patchright 过 CF
    print("\n[阶段 1] patchright 过 CF ...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, proxy={"server": proxy_server})
        context = await browser.new_context()
        page = await context.new_page()
        try:
            await page.goto("https://build.nvidia.com/?modal=signin", wait_until="domcontentloaded", timeout=60000)
            for i in range(60):
                await page.wait_for_timeout(1000)
                if await page.locator("input[name='email'], input[type='email']").count() > 0:
                    break
            email_loc = page.locator("input[name='email'], input[type='email']").first
            await email_loc.click(timeout=5000)
            await email_loc.fill(test_email)
            await page.wait_for_timeout(1000)
            await page.evaluate("""() => {
                const b = Array.from(document.querySelectorAll('button')).filter(b => b.offsetParent !== null).find(b => b.textContent.trim() === 'Next');
                if (b) b.click();
            }""")
            for i in range(60):
                await page.wait_for_timeout(500)
                if "nvgs" in page.url:
                    for j in range(30):
                        await page.wait_for_timeout(1000)
                        if await page.locator("input[type='password']").count() > 0:
                            break
                    break
            cookies = await context.cookies()
            cookie_dict = {c["name"]: c["value"] for c in cookies}
            ua = await page.evaluate("() => navigator.userAgent")
            nvgs_url = page.url
        finally:
            await browser.close()

    parsed = urlparse(nvgs_url)
    key = parse_qs(parsed.query).get("key", [None])[0]
    print(f"  key: {key[:30]}...")

    # 阶段 2: curl_cffi 注册
    print("\n[阶段 2] curl_cffi 注册 ...")
    session = cc_requests.Session(impersonate="chrome145")
    session.proxies = {"http": proxy_server, "https": proxy_server}
    for name, value in cookie_dict.items():
        session.cookies.set(name, value, domain=".nvidia.com")

    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "user-agent": ua,
        "origin": "https://login.nvgs.nvidia.com",
        "referer": "https://login.nvgs.nvidia.com/",
        "authorization": f"Bearer {key}",
    }

    # 2.1 获取 validation
    print("\n[API] 1. GET validator/register ...")
    resp = session.get(f"{API_BASE}/api/1/validator/register", headers=headers, timeout=30)
    print(f"  HTTP {resp.status_code}")
    validation_data = resp.json().get("validation", {})
    print(f"  validation keys: {list(validation_data.keys())}")

    # 2.2 解 hCaptcha
    print("\n[API] 2. 解 hCaptcha ...")
    hcaptcha_token = ""
    try:
        from captcha.hcaptcha.captcharun.provider import CaptchaRunHCaptchaProvider
        config = json.load(open(root_dir / "data" / "config.json", "r", encoding="utf-8"))
        hc_config = config.get("captcha", {}).get("hcaptcha", {}).get("captcharun", {})
        provider = CaptchaRunHCaptchaProvider()
        provider.configure(hc_config)
        hcaptcha_token = await provider.solve(sitekey=HCAPTCHA_SITEKEY, page_url=nvgs_url)
        print(f"  token: {hcaptcha_token[:30]}...")
    except Exception as e:
        print(f"  ❌ hCaptcha 失败: {e}")
        return

    # 2.3 设置 validation.response = hCaptcha token
    validation_data["response"] = hcaptcha_token
    print(f"\n  validation 完整: {json.dumps(validation_data, indent=2)[:300]}")

    # 2.4 注册
    print("\n[API] 3. POST user/register ...")
    register_data = {
        "email": test_email,
        "password": test_password,
        "confirmPassword": test_password,
        "validation": validation_data,
        "data_general_agreement": True,
    }
    print(f"  请求字段: {list(register_data.keys())}")

    resp = session.post(f"{API_BASE}/api/1/frontend/oauth/user/register",
                        headers=headers, json=register_data, timeout=30)
    print(f"\n  HTTP {resp.status_code}")
    print(f"  resp: {resp.text[:500]}")

    if resp.status_code in (200, 201):
        print(f"\n✅✅✅ 创建账户成功！")
        print(f"  邮箱: {test_email}")

        # 检查是否需要 OTP
        try:
            resp_data = resp.json()
            print(f"  响应: {json.dumps(resp_data, indent=2)[:300]}")
        except:
            pass

        # 等待 OTP - 用邮箱 Provider 自动获取
        print(f"\n[API] 4. 等待邮箱验证码 ...")
        code = ""
        try:
            from mailsys.cloudflare_worker.provider import PROVIDER as email_provider
            email_config = config.get("email", {}).get("cloudflare_worker", {})
            email_provider.configure(email_config)
            code = await email_provider.wait_code(test_email, timeout=120)
            print(f"  验证码: {code}")
        except Exception as e:
            print(f"  ❌ 邮箱获取失败: {e}")

        if code:
            # 提交 OTP - 用注册返回的新 key
            print(f"\n[API] 5. 提交 OTP ...")
            new_key = resp_data.get("key", key) if 'resp_data' in dir() else key
            otp_headers = {**headers, "authorization": f"Bearer {new_key}"}

            # 尝试多种 OTP 端点
            otp_endpoints = [
                "/api/1/frontend/oauth/user/verify",
                "/api/1/frontend/oauth/user/verify/email",
                "/api/1/frontend/oauth/user/otp",
                "/api/1/frontend/oauth/user/verify/otp",
                "/api/1/frontend/oauth/verify",
            ]
            otp_data = {"code": code}

            for ep in otp_endpoints:
                print(f"  尝试 {ep} ...")
                resp = session.post(f"{API_BASE}{ep}", headers=otp_headers, json=otp_data, timeout=30)
                print(f"  HTTP {resp.status_code} {resp.text[:200]}")
                if resp.status_code in (200, 201):
                    print(f"  ✅ OTP 验证成功！")
                    break
                elif resp.status_code != 404:
                    # 非 404 说明端点存在
                    break
        else:
            print("  ❌ 未获取到验证码")
    else:
        print(f"\n❌ 注册失败")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(test_hybrid_v7())
