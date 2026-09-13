"""NVIDIA - 扩大 OTP 端点搜索 + 尝试 user/register 带 code

注册成功后用新 key 测试更多端点
"""
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))


async def test_otp_extended():
    """扩大 OTP 端点搜索"""
    print("=" * 60)
    print("NVIDIA - 扩大 OTP 端点搜索")
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

    config = json.load(open(root_dir / "data" / "config.json", "r", encoding="utf-8"))

    # ═══ 阶段 1: patchright 过 CF ═══
    print("\n[1] patchright 过 CF ...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, proxy={"server": proxy_server})
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
    print("\n[2] curl_cffi 注册 ...")
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

    resp = session.get(f"{API_BASE}/api/1/validator/register", headers=headers, timeout=30)
    validation_data = resp.json().get("validation", {})

    from captcha.hcaptcha.captcharun.provider import CaptchaRunHCaptchaProvider
    hc_config = config.get("captcha", {}).get("hcaptcha", {}).get("captcharun", {})
    provider = CaptchaRunHCaptchaProvider()
    provider.configure(hc_config)
    hcaptcha_token = await provider.solve(sitekey=HCAPTCHA_SITEKEY, page_url=nvgs_url)

    validation_data["response"] = hcaptcha_token
    register_data = {
        "email": test_email, "password": test_password, "confirmPassword": test_password,
        "validation": validation_data, "data_general_agreement": True,
    }
    resp = session.post(f"{API_BASE}/api/1/frontend/oauth/user/register",
                        headers=headers, json=register_data, timeout=30)
    print(f"  注册 HTTP {resp.status_code}")

    if resp.status_code != 201:
        print(f"  ❌ 注册失败")
        return

    new_key = resp.json().get("key", key)
    print(f"  ✅ 注册成功！新 key: {new_key[:30]}...")

    # 邮箱验证码
    print("\n[3] 等待邮箱验证码 ...")
    from mailsys.cloudflare_worker.provider import PROVIDER as email_provider
    email_config = config.get("email", {}).get("cloudflare_worker", {})
    email_provider.configure(email_config)
    code = await email_provider.wait_code(test_email, timeout=120)
    print(f"  验证码: {code}")

    if not code:
        print("  ❌ 未获取到验证码")
        return

    # ═══ 阶段 3: 扩大 OTP 端点搜索 ═══
    print(f"\n[4] 测试 OTP 端点（扩大范围）...")

    otp_headers = {**headers, "authorization": f"Bearer {new_key}"}

    # 更多的端点变体
    endpoints = [
        # 不带 frontend
        ("POST", "/api/1/oauth/user/verify"),
        ("POST", "/api/1/oauth/user/confirm"),
        ("POST", "/api/1/oauth/verify"),
        ("POST", "/api/1/oauth/confirm"),
        # 不带 oauth
        ("POST", "/api/1/frontend/user/verify"),
        ("POST", "/api/1/frontend/user/confirm"),
        ("POST", "/api/1/frontend/verify"),
        ("POST", "/api/1/frontend/confirm"),
        # 不带 frontend/oauth
        ("POST", "/api/1/user/verify"),
        ("POST", "/api/1/user/confirm"),
        ("POST", "/api/1/verify"),
        ("POST", "/api/1/confirm"),
        # verifyEmail / emailVerify 驼峰
        ("POST", "/api/1/frontend/oauth/user/verifyEmail"),
        ("POST", "/api/1/frontend/oauth/user/emailVerify"),
        ("POST", "/api/1/frontend/oauth/verifyEmail"),
        ("POST", "/api/1/frontend/oauth/emailVerify"),
        # account 系列
        ("POST", "/api/1/frontend/oauth/account/verify"),
        ("POST", "/api/1/frontend/oauth/account/confirm"),
        ("POST", "/api/1/frontend/oauth/account/validate"),
        # code 系列
        ("POST", "/api/1/frontend/oauth/user/code"),
        ("POST", "/api/1/frontend/oauth/code"),
        ("POST", "/api/1/frontend/oauth/user/code/verify"),
        # register 系列（第二次调用？）
        ("POST", "/api/1/frontend/oauth/user/register/verify"),
        ("POST", "/api/1/frontend/oauth/user/register/confirm"),
        ("POST", "/api/1/frontend/oauth/user/register/complete"),
        # validate / complete
        ("POST", "/api/1/frontend/oauth/user/complete"),
        ("POST", "/api/1/frontend/oauth/user/activate"),
        ("POST", "/api/1/frontend/oauth/user/activate/email"),
        # resend 系列
        ("POST", "/api/1/frontend/oauth/user/resend/code"),
        ("POST", "/api/1/frontend/oauth/user/resend/otp"),
        ("POST", "/api/1/frontend/oauth/user/resend/email"),
    ]

    data_variants = [
        {"code": code},
        {"code": code, "email": test_email},
        {"verificationCode": code},
        {"otp": code},
        {"emailCode": code},
    ]

    print(f"\n{'端点':<55} {'数据':<30} {'状态':>4} {'响应'}")
    print("-" * 120)

    found = []
    for method, ep in endpoints:
        for data in data_variants:
            resp = session.post(f"{API_BASE}{ep}", headers=otp_headers, json=data, timeout=15)
            status = resp.status_code
            if status != 404:
                data_str = json.dumps(data)[:30]
                marker = "✅" if status in (200, 201) else "⚠️"
                print(f"{marker} {ep:<53} {data_str:<30} {status:>4} {resp.text[:60]}")
                found.append((ep, data, status, resp.text[:100]))
                if status in (200, 201):
                    break
            # 只在第一个 data 变体测试 404（避免重复）
            else:
                if data == data_variants[0]:
                    pass  # 静默跳过 404
                continue
            break
        else:
            continue
        if found and found[-1][2] in (200, 201):
            break

    # 特别测试：user/register 带 code
    print(f"\n[5] 特别测试: user/register 带 code ...")
    register_with_code = {
        **register_data,
        "validation": validation_data,
        "code": code,
    }
    resp = session.post(f"{API_BASE}/api/1/frontend/oauth/user/register",
                        headers=otp_headers, json=register_with_code, timeout=30)
    print(f"  user/register + code: HTTP {resp.status_code} {resp.text[:200]}")

    # 特别测试：user/register 只带 code
    resp = session.post(f"{API_BASE}/api/1/frontend/oauth/user/register",
                        headers=otp_headers, json={"code": code}, timeout=30)
    print(f"  user/register code only: HTTP {resp.status_code} {resp.text[:200]}")

    print(f"\n{'='*60}")
    if found:
        print(f"找到的非 404 端点:")
        for ep, data, status, body in found:
            print(f"  {ep} → {status} {body[:80]}")
    else:
        print(f"所有端点都返回 404")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(test_otp_extended())
