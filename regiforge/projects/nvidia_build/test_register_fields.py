"""在浏览器中用 fetch + Authorization 调用 user/register

错误: {"error":"SCHEMA_VIOLATION","details":[{"field":"validation","reason":"FIELD_REQUIRED"}]}
缺少 validation 字段

尝试各种字段组合，找到正确的格式
"""
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))


async def test_register_fields():
    """在浏览器中测试 user/register 的字段组合"""
    print("=" * 60)
    print("NVIDIA - 在浏览器中测试 user/register 字段")
    print("=" * 60)

    from patchright.async_api import async_playwright
    import random

    test_email = f"{''.join(str(random.randint(0, 9)) for _ in range(8))}@zhoushu.kdns.fr"
    test_password = "zs1236547."
    proxy_server = "http://127.0.0.1:7897"
    HCAPTCHA_SITEKEY = "3443d8f6-da7a-4326-929f-4d7fc89ab0d1"

    print(f"\n📧 邮箱: {test_email}")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, proxy={"server": proxy_server})
        context = await browser.new_context()
        page = await context.new_page()

        try:
            # 过 CF + 填邮箱 + 点 Next
            print("\n[1] 过 CF + 填邮箱 ...")
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
                            print(f"  表单加载")
                            break
                    break

            # 提取 key
            parsed = urlparse(page.url)
            params = parse_qs(parsed.query)
            key = params.get("key", [None])[0]
            print(f"  key: {key[:30]}...")

            # 解 hCaptcha
            print("\n[2] 解 hCaptcha ...")
            hcaptcha_token = ""
            try:
                from captcha.hcaptcha.captcharun.provider import CaptchaRunHCaptchaProvider
                config = json.load(open(root_dir / "data" / "config.json", "r", encoding="utf-8"))
                hc_config = config.get("captcha", {}).get("hcaptcha", {}).get("captcharun", {})
                provider = CaptchaRunHCaptchaProvider()
                provider.configure(hc_config)
                hcaptcha_token = await provider.solve(sitekey=HCAPTCHA_SITEKEY, page_url=page.url)
                print(f"  token: {hcaptcha_token[:30]}...")
            except Exception as e:
                print(f"  ❌ hCaptcha 失败: {e}")
                return

            # 在浏览器中用 fetch 测试各种字段组合
            print(f"\n[3] 在浏览器中用 fetch 测试字段组合 ...")

            # 所有字段组合
            combos = [
                # 组合 1: 添加 validation 字段
                {
                    "email": test_email,
                    "password": test_password,
                    "confirmPassword": test_password,
                    "validation": hcaptcha_token,
                    "data_general_agreement": True,
                },
                # 组合 2: validation 是对象
                {
                    "email": test_email,
                    "password": test_password,
                    "confirmPassword": test_password,
                    "validation": {"hCaptchaResponse": hcaptcha_token},
                    "agreements": [{"name": "data_general_agreement", "value": True}],
                },
                # 组合 3: validation 包含多种验证
                {
                    "email": test_email,
                    "password": test_password,
                    "confirmPassword": test_password,
                    "validation": {
                        "hCaptchaResponse": hcaptcha_token,
                        "h-captcha-response": hcaptcha_token,
                    },
                    "data_general_agreement": True,
                },
                # 组合 4: 带 deviceId
                {
                    "email": test_email,
                    "password": test_password,
                    "confirmPassword": test_password,
                    "validation": hcaptcha_token,
                    "deviceId": "testDeviceId123456",
                    "data_general_agreement": True,
                },
                # 组合 5: validation 是 hCaptcha 对象
                {
                    "email": test_email,
                    "password": test_password,
                    "confirmPassword": test_password,
                    "validation": {
                        "captchaType": "hCaptcha",
                        "token": hcaptcha_token,
                    },
                    "agreements": [{"name": "data_general_agreement", "value": True}],
                },
                # 组合 6: 最简 - 只有必填字段
                {
                    "email": test_email,
                    "password": test_password,
                    "validation": hcaptcha_token,
                },
                # 组合 7: agreements 是字典
                {
                    "email": test_email,
                    "password": test_password,
                    "confirmPassword": test_password,
                    "validation": hcaptcha_token,
                    "agreements": {"data_general_agreement": True},
                },
                # 组合 8: validation + agreements 数组
                {
                    "email": test_email,
                    "password": test_password,
                    "confirmPassword": test_password,
                    "validation": hcaptcha_token,
                    "agreements": [{"name": "data_general_agreement", "value": True, "version": "1.0"}],
                },
            ]

            results = await page.evaluate("""async (data) => {
                const {combos, key, apiUrl} = data;
                const results = [];

                for (const combo of combos) {
                    try {
                        const resp = await fetch(`${apiUrl}/api/1/frontend/oauth/user/register`, {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'Authorization': `Bearer ${key}`,
                            },
                            body: JSON.stringify(combo),
                        });
                        const text = await resp.text();
                        results.push({
                            fields: Object.keys(combo),
                            status: resp.status,
                            body: text.substring(0, 300),
                        });

                        // 如果成功，停止
                        if (resp.status === 200 || resp.status === 201) {
                            break;
                        }
                    } catch (e) {
                        results.push({
                            fields: Object.keys(combo),
                            status: -1,
                            body: e.message.substring(0, 100),
                        });
                    }
                }
                return results;
            }""", {"combos": combos, "key": key, "apiUrl": "https://accounts.nvgs.nvidia.com"})

            print(f"\n{'组合':<5} {'字段':<60} {'状态':>4} {'响应'}")
            print("-" * 120)
            for idx, r in enumerate(results):
                fields = ", ".join(r["fields"])
                marker = "✅" if r["status"] in (200, 201) else "  "
                print(f"{marker} {idx+1:<4} {fields:<60} {r['status']:>4} {r['body'][:80]}")

            # 找到成功的
            print(f"\n=== 结果 ===")
            for idx, r in enumerate(results):
                if r["status"] in (200, 201):
                    print(f"✅ 组合 {idx+1} 成功！")
                    print(f"  字段: {r['fields']}")
                    print(f"  响应: {r['body']}")
                elif r["status"] == 400:
                    print(f"⚠️ 组合 {idx+1}: 400 - {r['body'][:100]}")

        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(test_register_fields())
