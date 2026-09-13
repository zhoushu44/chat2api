"""检查 validator/register 和 validation 相关的 API

错误: validation 字段格式不对
可能 validation 是密码验证结果，不是 hCaptcha
"""
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))


async def check_validation_api():
    """检查 validation 相关 API"""
    print("=" * 60)
    print("NVIDIA - 检查 validation 相关 API")
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

            # 解 hCaptcha
            print("\n解 hCaptcha ...")
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

            # 在浏览器中调用各种 validation API
            print(f"\n[API] 检查 validation 相关 API ...")
            results = await page.evaluate("""async (data) => {
                const {key, password, email, hcaptchaToken} = data;
                const baseUrl = 'https://accounts.nvgs.nvidia.com';
                const headers = {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${key}`,
                };
                const results = [];

                // 1. GET /api/1/validator/register
                try {
                    const r = await fetch(`${baseUrl}/api/1/validator/register`, {headers});
                    results.push({api: 'GET /api/1/validator/register', status: r.status, body: (await r.text()).substring(0, 300)});
                } catch (e) { results.push({api: 'GET /api/1/validator/register', status: -1, body: e.message}); }

                // 2. POST /api/1/validator/register
                try {
                    const r = await fetch(`${baseUrl}/api/1/validator/register`, {
                        method: 'POST', headers,
                        body: JSON.stringify({email, password}),
                    });
                    results.push({api: 'POST /api/1/validator/register', status: r.status, body: (await r.text()).substring(0, 300)});
                } catch (e) { results.push({api: 'POST /api/1/validator/register', status: -1, body: e.message}); }

                // 3. POST /api/1/validator/register with password + confirmPassword
                try {
                    const r = await fetch(`${baseUrl}/api/1/validator/register`, {
                        method: 'POST', headers,
                        body: JSON.stringify({email, password, confirmPassword: password}),
                    });
                    results.push({api: 'POST /api/1/validator/register (with confirm)', status: r.status, body: (await r.text()).substring(0, 300)});
                } catch (e) { results.push({api: 'POST /api/1/validator/register (with confirm)', status: -1, body: e.message}); }

                // 4. GET /api/1/validation
                try {
                    const r = await fetch(`${baseUrl}/api/1/validation`, {headers});
                    results.push({api: 'GET /api/1/validation', status: r.status, body: (await r.text()).substring(0, 300)});
                } catch (e) { results.push({api: 'GET /api/1/validation', status: -1, body: e.message}); }

                // 5. POST /api/1/validation
                try {
                    const r = await fetch(`${baseUrl}/api/1/validation`, {
                        method: 'POST', headers,
                        body: JSON.stringify({password}),
                    });
                    results.push({api: 'POST /api/1/validation', status: r.status, body: (await r.text()).substring(0, 300)});
                } catch (e) { results.push({api: 'POST /api/1/validation', status: -1, body: e.message}); }

                // 6. GET /api/1/password/validation
                try {
                    const r = await fetch(`${baseUrl}/api/1/password/validation?password=${encodeURIComponent(password)}`, {headers});
                    results.push({api: 'GET /api/1/password/validation?password=xxx', status: r.status, body: (await r.text()).substring(0, 300)});
                } catch (e) { results.push({api: 'GET /api/1/password/validation', status: -1, body: e.message}); }

                // 7. POST /api/1/password/validation
                try {
                    const r = await fetch(`${baseUrl}/api/1/password/validation`, {
                        method: 'POST', headers,
                        body: JSON.stringify({password}),
                    });
                    results.push({api: 'POST /api/1/password/validation', status: r.status, body: (await r.text()).substring(0, 300)});
                } catch (e) { results.push({api: 'POST /api/1/password/validation', status: -1, body: e.message}); }

                // 8. user/register with validation = {password validation result}
                // 先获取密码验证结果
                let pwdValidation = null;
                try {
                    const r = await fetch(`${baseUrl}/api/1/password/validation`, {
                        method: 'POST', headers,
                        body: JSON.stringify({password}),
                    });
                    pwdValidation = await r.text();
                } catch {}

                // 9. user/register with validation 包含密码验证
                if (pwdValidation) {
                    try {
                        const pwdData = JSON.parse(pwdValidation);
                        const r = await fetch(`${baseUrl}/api/1/frontend/oauth/user/register`, {
                            method: 'POST', headers,
                            body: JSON.stringify({
                                email, password, confirmPassword: password,
                                validation: pwdData,
                                hCaptchaResponse: hcaptchaToken,
                                data_general_agreement: true,
                            }),
                        });
                        results.push({api: 'user/register with pwd validation', status: r.status, body: (await r.text()).substring(0, 300)});
                    } catch (e) { results.push({api: 'user/register with pwd validation', status: -1, body: e.message}); }
                }

                return results;
            }""", {"key": key, "password": test_password, "email": test_email, "hcaptchaToken": hcaptcha_token})

            print(f"\n{'API':<55} {'状态':>4} {'响应'}")
            print("-" * 120)
            for r in results:
                marker = "✅" if r["status"] in (200, 201) else "  "
                print(f"{marker} {r['api']:<53} {r['status']:>4} {r['body'][:80]}")

        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(check_validation_api())
