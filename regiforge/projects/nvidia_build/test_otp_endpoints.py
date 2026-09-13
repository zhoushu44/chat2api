"""NVIDIA - 完整注册 + OTP 端点测试

在浏览器中用 fetch 测试 OTP 验证端点
"""
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))


async def test_otp_endpoints():
    """完整注册 + OTP 端点测试"""
    print("=" * 60)
    print("NVIDIA - 完整注册 + OTP 端点测试")
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

    # ═══ 阶段 1: patchright 过 CF ═══
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

    # ═══ 阶段 2: curl_cffi 注册 ═══
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

    # 2.1 validator/register
    print("\n[API] validator/register ...")
    resp = session.get(f"{API_BASE}/api/1/validator/register", headers=headers, timeout=30)
    validation_data = resp.json().get("validation", {})

    # 2.2 hCaptcha
    print("[API] hCaptcha ...")
    config = json.load(open(root_dir / "data" / "config.json", "r", encoding="utf-8"))
    from captcha.hcaptcha.captcharun.provider import CaptchaRunHCaptchaProvider
    hc_config = config.get("captcha", {}).get("hcaptcha", {}).get("captcharun", {})
    provider = CaptchaRunHCaptchaProvider()
    provider.configure(hc_config)
    hcaptcha_token = await provider.solve(sitekey=HCAPTCHA_SITEKEY, page_url=nvgs_url)
    print(f"  token: {hcaptcha_token[:30]}...")

    # 2.3 注册
    validation_data["response"] = hcaptcha_token
    print("\n[API] user/register ...")
    register_data = {
        "email": test_email,
        "password": test_password,
        "confirmPassword": test_password,
        "validation": validation_data,
        "data_general_agreement": True,
    }
    resp = session.post(f"{API_BASE}/api/1/frontend/oauth/user/register",
                        headers=headers, json=register_data, timeout=30)
    print(f"  HTTP {resp.status_code}")

    if resp.status_code != 201:
        print(f"  ❌ 注册失败: {resp.text[:200]}")
        return

    new_key = resp.json().get("key", key)
    print(f"  ✅ 注册成功！新 key: {new_key[:30]}...")

    # 2.4 邮箱验证码
    print("\n[API] 等待邮箱验证码 ...")
    from mailsys.cloudflare_worker.provider import PROVIDER as email_provider
    email_config = config.get("email", {}).get("cloudflare_worker", {})
    email_provider.configure(email_config)
    code = await email_provider.wait_code(test_email, timeout=120)
    print(f"  验证码: {code}")

    if not code:
        print("  ❌ 未获取到验证码")
        return

    # 2.5 测试 OTP 端点（用 curl_cffi）
    print(f"\n[API] 测试 OTP 端点（用新 key）...")
    otp_headers = {**headers, "authorization": f"Bearer {new_key}"}

    otp_endpoints = [
        # user/ 系列
        ("POST", "/api/1/frontend/oauth/user/verify"),
        ("POST", "/api/1/frontend/oauth/user/verify/email"),
        ("POST", "/api/1/frontend/oauth/user/confirm"),
        ("POST", "/api/1/frontend/oauth/user/email/verify"),
        ("POST", "/api/1/frontend/oauth/user/email/confirm"),
        ("POST", "/api/1/frontend/oauth/user/validate"),
        ("POST", "/api/1/frontend/oauth/user/verification"),
        ("POST", "/api/1/frontend/oauth/user/otp/verify"),
        ("POST", "/api/1/frontend/oauth/user/otp/confirm"),
        ("POST", "/api/1/frontend/oauth/user/otp"),
        # verify 系列
        ("POST", "/api/1/frontend/oauth/verify"),
        ("POST", "/api/1/frontend/oauth/verify/email"),
        ("POST", "/api/1/frontend/oauth/verify/otp"),
        ("POST", "/api/1/frontend/oauth/email/verify"),
        ("POST", "/api/1/frontend/oauth/otp/verify"),
        ("POST", "/api/1/frontend/oauth/otp"),
        ("POST", "/api/1/frontend/oauth/confirm"),
        # validator 系列
        ("GET",  "/api/1/validator/verify"),
        ("GET",  "/api/1/validator/otp"),
        ("GET",  "/api/1/validator/email"),
        # 其他
        ("POST", "/api/1/frontend/oauth/user/resend"),
        ("POST", "/api/1/frontend/oauth/user/verify/code"),
    ]

    otp_data_variants = [
        {"code": code},
        {"code": code, "email": test_email},
        {"otp": code},
        {"verificationCode": code},
        {"email": test_email, "code": code},
    ]

    print(f"\n{'端点':<55} {'状态':>4} {'响应'}")
    print("-" * 100)

    found_endpoint = None
    for method, ep in otp_endpoints:
        for data in otp_data_variants:
            if method == "GET":
                resp = session.get(f"{API_BASE}{ep}", headers=otp_headers, timeout=15)
            else:
                resp = session.post(f"{API_BASE}{ep}", headers=otp_headers, json=data, timeout=15)

            status = resp.status_code
            if status != 404:
                marker = "✅" if status in (200, 201) else "⚠️"
                print(f"{marker} {method} {ep:<50} {status:>4} {resp.text[:80]}")
                if status in (200, 201):
                    found_endpoint = (method, ep, data)
                    break
                elif status in (400, 401, 403):
                    # 端点存在但参数不对
                    if not found_endpoint:
                        found_endpoint = (method, ep, data)
                    break
        else:
            print(f"   {method} {ep:<50} {'404':>4}")
            continue
        break

    if found_endpoint:
        method, ep, data = found_endpoint
        print(f"\n✅ 找到 OTP 端点: {method} {ep}")
        print(f"  数据: {data}")
        print(f"  响应: {resp.text[:300]}")
    else:
        print(f"\n❌ 未找到 OTP 端点")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(test_otp_endpoints())
