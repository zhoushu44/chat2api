"""NVIDIA 混合模式 v4 - 完整 API 调用（带 Authorization）

关键发现:
  1. POST API 需要 Authorization: Bearer <key> header
  2. key 就是 NVGS URL 中的 key 参数（JWT token）
  3. hCaptcha sitekey: 3443d8f6-da7a-4326-929f-4d7fc89ab0d1
  4. API 域名: accounts.nvgs.nvidia.com
"""
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))


async def test_hybrid_v4():
    """测试混合模式 v4 - 带 Authorization header"""
    print("=" * 60)
    print("NVIDIA 混合模式 v4 - 带 Authorization")
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

    # ═══ 阶段 1: patchright 过 CF + 提取 Cookie ═══
    print("\n[阶段 1] patchright 过 CF + 提取 Cookie ...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, proxy={"server": proxy_server})
        context = await browser.new_context()
        page = await context.new_page()

        try:
            await page.goto("https://build.nvidia.com/?modal=signin", wait_until="domcontentloaded", timeout=60000)

            for i in range(60):
                await page.wait_for_timeout(1000)
                if await page.locator("input[name='email'], input[type='email']").count() > 0:
                    print(f"  CF 过了 ({i+1}s)")
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
                            print(f"  注册表单加载 ({i*0.5+0.5}s + {j+1}s)")
                            break
                    break

            cookies = await context.cookies()
            cookie_dict = {c["name"]: c["value"] for c in cookies}
            ua = await page.evaluate("() => navigator.userAgent")
            nvgs_url = page.url

        finally:
            await browser.close()

    # 提取 key
    parsed = urlparse(nvgs_url)
    params = parse_qs(parsed.query)
    key = params.get("key", [None])[0]
    print(f"  key: {key[:40]}...")

    # ═══ 阶段 2: curl_cffi 调 API（带 Authorization）═══
    print("\n[阶段 2] curl_cffi 调 API（带 Authorization: Bearer）...")

    session = cc_requests.Session(impersonate="chrome145")
    session.proxies = {"http": proxy_server, "https": proxy_server}

    for name, value in cookie_dict.items():
        session.cookies.set(name, value, domain=".nvidia.com")

    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-US,en;q=0.9",
        "content-type": "application/json",
        "user-agent": ua,
        "origin": "https://login.nvgs.nvidia.com",
        "referer": "https://login.nvgs.nvidia.com/",
        "authorization": f"Bearer {key}",  # ← 关键！
    }

    # 1. initialize/check
    print("\n[API] 1. initialize/check ...")
    resp = session.post(
        f"{API_BASE}/api/1/frontend/oauth/initialize/check",
        headers=headers,
        json={"browserMode": "Normal", "passkeySupported": False},
        timeout=30,
    )
    print(f"  HTTP {resp.status_code}")
    print(f"  resp: {resp.text[:300]}")

    # 2. account/check
    print("\n[API] 2. account/check ...")
    resp = session.post(
        f"{API_BASE}/api/1/frontend/oauth/account/check",
        headers=headers,
        json={"email": test_email, "rememberLogin": True, "deviceId": "test_device_id"},
        timeout=30,
    )
    print(f"  HTTP {resp.status_code}")
    print(f"  resp: {resp.text[:300]}")

    # 3. email/check
    print("\n[API] 3. email/check ...")
    resp = session.post(
        f"{API_BASE}/api/1/frontend/oauth/email/check",
        headers=headers,
        json={"email": test_email},
        timeout=30,
    )
    print(f"  HTTP {resp.status_code}")
    print(f"  resp: {resp.text[:300]}")

    # 4. 尝试多种创建账户端点
    print("\n[API] 4. 尝试创建账户 ...")

    # 解 hCaptcha
    print("  解 hCaptcha ...")
    hcaptcha_token = ""
    try:
        from captcha.hcaptcha.captcharun.provider import CaptchaRunHCaptchaProvider
        config = json.load(open(root_dir / "data" / "config.json", "r", encoding="utf-8"))
        hc_config = config.get("captcha", {}).get("hcaptcha", {}).get("captcharun", {})
        provider = CaptchaRunHCaptchaProvider()
        provider.configure(hc_config)
        hcaptcha_token = await provider.solve(
            sitekey=HCAPTCHA_SITEKEY,
            page_url=nvgs_url,
        )
        print(f"  hCaptcha token: {hcaptcha_token[:30] if hcaptcha_token else 'None'}...")
    except Exception as e:
        print(f"  hCaptcha 失败: {e}")

    if hcaptcha_token:
        # 尝试多种字段名和端点
        endpoints = [
            "/api/1/frontend/oauth/account/create",
            "/api/1/frontend/oauth/register",
            "/api/1/frontend/oauth/create-account",
        ]

        field_variants = [
            {
                "email": test_email,
                "password": test_password,
                "confirmPassword": test_password,
                "hCaptchaResponse": hcaptcha_token,
                "agreements": [{"name": "data_general_agreement", "value": True}],
            },
            {
                "email": test_email,
                "password": test_password,
                "confirmPassword": test_password,
                "h-captcha-response": hcaptcha_token,
                "data_general_agreement": True,
            },
        ]

        for ep in endpoints:
            for fv in field_variants:
                print(f"\n  POST {ep}")
                print(f"  fields: {list(fv.keys())}")
                resp = session.post(
                    f"{API_BASE}{ep}",
                    headers=headers,
                    json=fv,
                    timeout=30,
                )
                print(f"  HTTP {resp.status_code}")
                print(f"  resp: {resp.text[:200]}")

                if resp.status_code in (200, 201):
                    print(f"\n✅✅✅ 找到正确的创建账户端点！")
                    print(f"  endpoint: {ep}")
                    print(f"  fields: {list(fv.keys())}")
                    break
                elif resp.status_code != 404:
                    # 非 404 说明端点存在，只是参数不对
                    print(f"  ⚠️ 端点存在但参数不对")
                    break
            else:
                continue
            break

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_hybrid_v4())
