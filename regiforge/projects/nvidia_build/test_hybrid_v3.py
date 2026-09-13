"""NVIDIA 混合模式 v3 - 使用真实 API 端点

关键发现（抓包）:
  API 域名: accounts.nvgs.nvidia.com
  hCaptcha sitekey: 3443d8f6-da7a-4326-929f-4d7fc89ab0d1

API 端点:
  POST /api/1/frontend/oauth/initialize/check  - 初始化
  POST /api/1/frontend/oauth/account/check     - 检查账号
  POST /api/1/frontend/oauth/email/check       - 邮箱检查
  GET  /api/1/validator/register               - 注册验证
  GET  /api/1/password/validation/policy       - 密码策略
  POST /api/1/frontend/oauth/account/create    - 创建账户（推测）

流程:
  阶段 1 (patchright): 过 CF → 填邮箱 → 点 Next → 提取 Cookie
  阶段 2 (curl_cffi):  调 API 注册 → OTP → API Key
"""
import asyncio
import json
import sys
from pathlib import Path

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))


async def test_hybrid_v3():
    """测试混合模式 v3 - 用真实 API 端点"""
    print("=" * 60)
    print("NVIDIA 混合模式 v3 - 真实 API 端点测试")
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
    print(f"📡 代理: {proxy_server}")
    print(f"🔑 sitekey: {HCAPTCHA_SITEKEY}")
    print("=" * 60)

    # ═══════════════════════════════════════════
    # 阶段 1: patchright 过 CF + 提取 Cookie
    # ═══════════════════════════════════════════
    print("\n[阶段 1] patchright 过 CF + 提取 Cookie ...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, proxy={"server": proxy_server})
        context = await browser.new_context()
        page = await context.new_page()

        try:
            await page.goto("https://build.nvidia.com/?modal=signin", wait_until="domcontentloaded", timeout=60000)

            # 等邮箱输入框
            for i in range(60):
                await page.wait_for_timeout(1000)
                if await page.locator("input[name='email'], input[type='email']").count() > 0:
                    print(f"  CF 过了 ({i+1}s)")
                    break

            # 填邮箱 + 点 Next
            email_loc = page.locator("input[name='email'], input[type='email']").first
            await email_loc.click(timeout=5000)
            await email_loc.fill(test_email)
            await page.wait_for_timeout(1000)
            await page.evaluate("""() => {
                const b = Array.from(document.querySelectorAll('button')).filter(b => b.offsetParent !== null).find(b => b.textContent.trim() === 'Next');
                if (b) b.click();
            }""")

            # 等跳转 + 注册表单
            for i in range(60):
                await page.wait_for_timeout(500)
                if "nvgs" in page.url:
                    for j in range(30):
                        await page.wait_for_timeout(1000)
                        if await page.locator("input[type='password']").count() > 0:
                            print(f"  注册表单加载 ({i*0.5+0.5}s + {j+1}s)")
                            break
                    break

            # 提取 Cookie + UA
            cookies = await context.cookies()
            cookie_dict = {c["name"]: c["value"] for c in cookies}
            ua = await page.evaluate("() => navigator.userAgent")
            nvgs_url = page.url
            print(f"  Cookie: {len(cookie_dict)} 个")
            print(f"  UA: {ua[:50]}...")

        finally:
            await browser.close()

    # ═══════════════════════════════════════════
    # 阶段 2: curl_cffi 调 API
    # ═══════════════════════════════════════════
    print("\n[阶段 2] curl_cffi 调用 API ...")

    session = cc_requests.Session(impersonate="chrome145")
    session.proxies = {"http": proxy_server, "https": proxy_server}

    # 设置 Cookie
    for name, value in cookie_dict.items():
        session.cookies.set(name, value, domain=".nvidia.com")

    # 提取 key 参数
    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(nvgs_url)
    params = parse_qs(parsed.query)
    key = params.get("key", [None])[0]
    client_id = params.get("client_id", [None])[0]
    print(f"  key: {key[:30] if key else 'None'}...")
    print(f"  client_id: {client_id}")

    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-US,en;q=0.9",
        "content-type": "application/json",
        "user-agent": ua,
        "origin": "https://login.nvgs.nvidia.com",
        "referer": nvgs_url,
    }

    # 2.1 initialize/check
    print("\n[API] 1. initialize/check ...")
    resp = session.post(
        f"{API_BASE}/api/1/frontend/oauth/initialize/check",
        headers=headers,
        json={"browserMode": "Normal", "passkeySupported": False},
        timeout=30,
    )
    print(f"  HTTP {resp.status_code}")
    print(f"  resp: {resp.text[:200]}")

    # 2.2 account/check
    print("\n[API] 2. account/check ...")
    resp = session.post(
        f"{API_BASE}/api/1/frontend/oauth/account/check",
        headers=headers,
        json={"email": test_email, "rememberLogin": True, "deviceId": "test_device_id"},
        timeout=30,
    )
    print(f"  HTTP {resp.status_code}")
    print(f"  resp: {resp.text[:200]}")

    # 2.3 email/check
    print("\n[API] 3. email/check ...")
    resp = session.post(
        f"{API_BASE}/api/1/frontend/oauth/email/check",
        headers=headers,
        json={"email": test_email},
        timeout=30,
    )
    print(f"  HTTP {resp.status_code}")
    print(f"  resp: {resp.text[:200]}")

    # 2.4 password policy
    print("\n[API] 4. password/validation/policy ...")
    resp = session.get(
        f"{API_BASE}/api/1/password/validation/policy",
        headers=headers,
        timeout=30,
    )
    print(f"  HTTP {resp.status_code}")
    print(f"  resp: {resp.text[:200]}")

    # 2.5 尝试创建账户
    print("\n[API] 5. 尝试创建账户 (account/create) ...")
    # 先解 hCaptcha
    print("  解 hCaptcha ...")
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
        hcaptcha_token = ""

    if hcaptcha_token:
        # 尝试创建账户
        create_data = {
            "email": test_email,
            "password": test_password,
            "confirmPassword": test_password,
            "hCaptchaResponse": hcaptcha_token,
            "agreements": [
                {"name": "data_general_agreement", "value": True},
            ],
        }
        print(f"  创建账户数据: {json.dumps(create_data, indent=2)[:300]}")

        resp = session.post(
            f"{API_BASE}/api/1/frontend/oauth/account/create",
            headers=headers,
            json=create_data,
            timeout=30,
        )
        print(f"  HTTP {resp.status_code}")
        print(f"  resp: {resp.text[:300]}")

        # 如果 404，尝试其他端点
        if resp.status_code == 404:
            print("\n  尝试 /api/1/frontend/oauth/register ...")
            resp = session.post(
                f"{API_BASE}/api/1/frontend/oauth/register",
                headers=headers,
                json=create_data,
                timeout=30,
            )
            print(f"  HTTP {resp.status_code}")
            print(f"  resp: {resp.text[:300]}")

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_hybrid_v3())
