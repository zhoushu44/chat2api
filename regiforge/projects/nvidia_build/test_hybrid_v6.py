"""NVIDIA 混合模式 v6 - 用 validator/register 获取 validation token

流程:
1. patchright 过 CF → 填邮箱 → 点 Next → 提取 key
2. curl_cffi:
   a. GET /api/1/validator/register → 获取 validation 对象
   b. POST /api/1/frontend/oauth/user/register → 用 validation 注册
"""
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))


async def test_hybrid_v6():
    """混合模式 v6 - 用 validator/register"""
    print("=" * 60)
    print("NVIDIA 混合模式 v6 - validator/register + user/register")
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

    # ═══ 阶段 1: patchright 过 CF + 提取 key ═══
    print("\n[阶段 1] patchright 过 CF + 提取 key ...")

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
                            print(f"  表单加载")
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

    # 2.1 获取 validation 对象
    print("\n[API] 1. GET /api/1/validator/register → 获取 validation ...")
    resp = session.get(f"{API_BASE}/api/1/validator/register", headers=headers, timeout=30)
    print(f"  HTTP {resp.status_code}")
    print(f"  resp: {resp.text[:200]}")

    if resp.status_code != 200:
        print("  ❌ 获取 validation 失败")
        return

    validation_data = resp.json()
    print(f"  validation: {json.dumps(validation_data, indent=2)[:300]}")

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

    # 2.3 用 validation 注册
    print("\n[API] 3. POST /api/1/frontend/oauth/user/register ...")

    # 尝试多种格式
    register_combos = [
        # 1: validation 直接传入
        {
            "email": test_email,
            "password": test_password,
            "confirmPassword": test_password,
            "validation": validation_data.get("validation"),
            "hCaptchaResponse": hcaptcha_token,
            "data_general_agreement": True,
        },
        # 2: validation + hCaptcha 放在 validation 里
        {
            "email": test_email,
            "password": test_password,
            "confirmPassword": test_password,
            "validation": {
                **validation_data.get("validation", {}),
                "hCaptchaResponse": hcaptcha_token,
            },
            "data_general_agreement": True,
        },
        # 3: validation 整个对象
        {
            "email": test_email,
            "password": test_password,
            "confirmPassword": test_password,
            "validation": validation_data,
            "hCaptchaResponse": hcaptcha_token,
            "data_general_agreement": True,
        },
        # 4: 只用 validation.key
        {
            "email": test_email,
            "password": test_password,
            "confirmPassword": test_password,
            "validation": validation_data.get("validation", {}),
            "agreements": [{"name": "data_general_agreement", "value": True}],
        },
    ]

    for idx, data in enumerate(register_combos):
        print(f"\n  组合 {idx+1}: {list(data.keys())}")
        if isinstance(data.get("validation"), dict):
            print(f"  validation keys: {list(data['validation'].keys())}")

        resp = session.post(f"{API_BASE}/api/1/frontend/oauth/user/register",
                            headers=headers, json=data, timeout=30)
        print(f"  HTTP {resp.status_code}")
        print(f"  resp: {resp.text[:300]}")

        if resp.status_code in (200, 201):
            print(f"\n✅✅✅ 创建账户成功！")
            break
        elif resp.status_code == 400:
            # 解析错误详情
            try:
                err = resp.json()
                print(f"  错误详情: {json.dumps(err, indent=2)[:200]}")
            except:
                pass

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_hybrid_v6())
