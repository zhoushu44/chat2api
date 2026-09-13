"""NVIDIA 混合模式 v5 - 用正确的 API 端点注册

关键发现:
  创建账户 API: POST /api/1/frontend/oauth/user/register
  需要: Authorization: Bearer <key>
  hCaptcha sitekey: 3443d8f6-da7a-4326-929f-4d7fc89ab0d1

流程:
  阶段 1 (patchright): 过 CF → 填邮箱 → 点 Next → 提取 Cookie/key
  阶段 2 (curl_cffi):  调 API 注册 → OTP → API Key
"""
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))


async def test_hybrid_v5():
    """混合模式 v5 - 用 user/register API"""
    print("=" * 60)
    print("NVIDIA 混合模式 v5 - user/register API")
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

    # ═══ 阶段 1: patchright 过 CF + 提取 Cookie/key ═══
    print("\n[阶段 1] patchright 过 CF + 提取 Cookie/key ...")

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
    print(f"  Cookie: {len(cookie_dict)} 个")

    # ═══ 阶段 2: curl_cffi 注册 ═══
    print("\n[阶段 2] curl_cffi 注册 ...")

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
        "authorization": f"Bearer {key}",
    }

    # 1. initialize/check
    print("\n[API] 1. initialize/check ...")
    resp = session.post(f"{API_BASE}/api/1/frontend/oauth/initialize/check",
                        headers=headers, json={"browserMode": "Normal", "passkeySupported": False}, timeout=30)
    print(f"  HTTP {resp.status_code} {resp.text[:100]}")

    # 2. email/check
    print("\n[API] 2. email/check ...")
    resp = session.post(f"{API_BASE}/api/1/frontend/oauth/email/check",
                        headers=headers, json={"email": test_email}, timeout=30)
    print(f"  HTTP {resp.status_code} {resp.text[:100]}")

    # 3. 解 hCaptcha
    print("\n[API] 3. 解 hCaptcha ...")
    hcaptcha_token = ""
    try:
        from captcha.hcaptcha.captcharun.provider import CaptchaRunHCaptchaProvider
        config = json.load(open(root_dir / "data" / "config.json", "r", encoding="utf-8"))
        hc_config = config.get("captcha", {}).get("hcaptcha", {}).get("captcharun", {})
        provider = CaptchaRunHCaptchaProvider()
        provider.configure(hc_config)
        hcaptcha_token = await provider.solve(sitekey=HCAPTCHA_SITEKEY, page_url=nvgs_url)
        print(f"  token: {hcaptcha_token[:40] if hcaptcha_token else 'None'}...")
    except Exception as e:
        print(f"  ❌ hCaptcha 失败: {e}")

    if not hcaptcha_token:
        print("\n❌ 无法获取 hCaptcha token")
        return

    # 4. user/register - 创建账户
    print("\n[API] 4. user/register (创建账户) ...")

    # 尝试多种字段名组合
    field_combos = [
        # 组合 1
        {
            "email": test_email,
            "password": test_password,
            "confirmPassword": test_password,
            "hCaptchaResponse": hcaptcha_token,
            "agreements": [{"name": "data_general_agreement", "value": True}],
        },
        # 组合 2
        {
            "email": test_email,
            "password": test_password,
            "confirmPassword": test_password,
            "h-captcha-response": hcaptcha_token,
            "data_general_agreement": True,
        },
        # 组合 3
        {
            "email": test_email,
            "password": test_password,
            "confirmPassword": test_password,
            "captchaToken": hcaptcha_token,
            "agreements": [{"name": "data_general_agreement", "value": True}],
        },
        # 组合 4 - 最小字段
        {
            "email": test_email,
            "password": test_password,
            "hCaptchaResponse": hcaptcha_token,
        },
        # 组合 5
        {
            "email": test_email,
            "password": test_password,
            "confirmPassword": test_password,
            "hcaptchaToken": hcaptcha_token,
            "data_general_agreement": True,
        },
    ]

    for idx, data in enumerate(field_combos):
        print(f"\n  尝试组合 {idx+1}: {list(data.keys())}")
        resp = session.post(f"{API_BASE}/api/1/frontend/oauth/user/register",
                            headers=headers, json=data, timeout=30)
        print(f"  HTTP {resp.status_code}")
        print(f"  resp: {resp.text[:300]}")

        if resp.status_code in (200, 201):
            print(f"\n✅✅✅ 创建账户成功！")
            print(f"  字段组合: {list(data.keys())}")
            break
        elif resp.status_code == 400:
            # 400 说明端点正确，只是参数不对
            print(f"  ⚠️ 参数不对（400），但端点正确！")
            # 继续尝试下一个组合
        elif resp.status_code == 401:
            print(f"  ⚠️ 认证失败（401）")
            break
        elif resp.status_code == 403:
            print(f"  ⚠️ 被拒绝（403）")
            break

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_hybrid_v5())
