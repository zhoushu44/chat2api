"""NVIDIA - 用新 key 导航到验证页面，抓包 OTP 提交

注册成功后返回新 key，用新 key 访问验证页面
"""
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))


async def test_verify_page():
    """注册后导航到验证页面，抓包 OTP"""
    print("=" * 60)
    print("NVIDIA - 验证页面 + OTP 抓包")
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
    print("\n[阶段 1] patchright 过 CF ...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, proxy={"server": proxy_server})
        context = await browser.new_context()
        page = await context.new_page()

        # 监控所有 POST 请求
        captured_posts = []
        def on_request(request):
            if request.method != "POST":
                return
            if any(x in request.url for x in ["datadoghq", "analytics", "client-logger", "akam", "awswaf"]):
                return
            entry = {"url": request.url, "post_data": request.post_data, "auth": request.headers.get("authorization", "")}
            captured_posts.append(entry)

        page.on("request", on_request)

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
            # 不关闭浏览器，继续用

            pass  # browser 在后面关闭

    parsed = urlparse(nvgs_url)
    key = parse_qs(parsed.query).get("key", [None])[0]
    client_id = parse_qs(parsed.query).get("client_id", [None])[0]
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

    # validator/register
    resp = session.get(f"{API_BASE}/api/1/validator/register", headers=headers, timeout=30)
    validation_data = resp.json().get("validation", {})

    # hCaptcha
    from captcha.hcaptcha.captcharun.provider import CaptchaRunHCaptchaProvider
    hc_config = config.get("captcha", {}).get("hcaptcha", {}).get("captcharun", {})
    provider = CaptchaRunHCaptchaProvider()
    provider.configure(hc_config)
    hcaptcha_token = await provider.solve(sitekey=HCAPTCHA_SITEKEY, page_url=nvgs_url)

    # 注册
    validation_data["response"] = hcaptcha_token
    register_data = {
        "email": test_email, "password": test_password, "confirmPassword": test_password,
        "validation": validation_data, "data_general_agreement": True,
    }
    resp = session.post(f"{API_BASE}/api/1/frontend/oauth/user/register",
                        headers=headers, json=register_data, timeout=30)
    print(f"  注册 HTTP {resp.status_code}")

    if resp.status_code != 201:
        print(f"  ❌ 注册失败: {resp.text[:200]}")
        await browser.close()
        return

    new_key = resp.json().get("key", key)
    print(f"  ✅ 注册成功！新 key: {new_key[:30]}...")

    # ═══ 阶段 3: 用新 key 导航到验证页面 ═══
    print("\n[阶段 3] 用新 key 导航到验证页面 ...")

    # 尝试多种验证页面 URL
    verify_urls = [
        f"https://login.nvgs.nvidia.com/v1/profile-complete?preferred_nvidia=true&context=Initial&theme=Noir&locale=zh-CN&prompt=default&email={test_email}&key={new_key}&client_id={client_id}",
        f"https://login.nvgs.nvidia.com/v1/verify?preferred_nvidia=true&key={new_key}&client_id={client_id}",
        f"https://login.nvgs.nvidia.com/v1/email-verify?key={new_key}&client_id={client_id}",
        f"https://login.nvgs.nvidia.com/v1/create-account?preferred_nvidia=true&key={new_key}&client_id={client_id}",
    ]

    for vurl in verify_urls:
        print(f"\n  尝试访问: {vurl[:80]}...")
        try:
            await page.goto(vurl, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)

            title = await page.title()
            url = page.url
            print(f"  Title: {title}")
            print(f"  URL: {url[:80]}")

            # 检查是否有 OTP 输入框
            otp_input = await page.evaluate("""() => {
                const inputs = document.querySelectorAll('input');
                const otpInputs = Array.from(inputs).filter(i => {
                    const text = [i.name, i.id, i.placeholder, i.type, i.getAttribute('inputmode')].join(' ').toLowerCase();
                    return /code|otp|verification|验证码/i.test(text) || i.maxLength === 1 || i.getAttribute('inputmode') === 'numeric';
                });
                return {
                    count: otpInputs.length,
                    details: otpInputs.map(i => ({name: i.name, id: i.id, type: i.type, maxlength: i.maxLength, placeholder: i.placeholder})),
                };
            }""")
            print(f"  OTP 输入框: {otp_input['count']} 个")
            if otp_input["details"]:
                for d in otp_input["details"]:
                    print(f"    {d}")

            if otp_input["count"] > 0:
                print(f"\n  ✅ 找到 OTP 验证页面！")

                # 获取邮箱验证码
                print("  等待邮箱验证码 ...")
                from mailsys.cloudflare_worker.provider import PROVIDER as email_provider
                email_config = config.get("email", {}).get("cloudflare_worker", {})
                email_provider.configure(email_config)
                code = await email_provider.wait_code(test_email, timeout=120)
                print(f"  验证码: {code}")

                if code:
                    # 输入验证码
                    print(f"  输入验证码: {code}")
                    # 尝试输入到 OTP 输入框
                    if otp_input["count"] == 1:
                        # 单个输入框
                        loc = page.locator("input").filter(has_text="")
                        await page.evaluate(f"""() => {{
                            const inputs = document.querySelectorAll('input');
                            const otpInput = Array.from(inputs).find(i => i.maxLength === 1 || /code|otp/i.test(i.name || i.id || ''));
                            if (otpInput) {{
                                otpInput.value = '{code}';
                                otpInput.dispatchEvent(new Event('input', {{bubbles: true}}));
                                otpInput.dispatchEvent(new Event('change', {{bubbles: true}}));
                            }}
                        }}""")
                    else:
                        # 多个单字符输入框
                        for idx, c in enumerate(code):
                            if idx < otp_input["count"]:
                                await page.evaluate(f"""() => {{
                                    const inputs = document.querySelectorAll('input');
                                    const otpInputs = Array.from(inputs).filter(i => i.maxLength === 1);
                                    if (otpInputs[{idx}]) {{
                                        otpInputs[{idx}].value = '{c}';
                                        otpInputs[{idx}].dispatchEvent(new Event('input', {{bubbles: true}}));
                                        otpInputs[{idx}].dispatchEvent(new Event('change', {{bubbles: true}}));
                                    }}
                                }}""")

                    await page.wait_for_timeout(2000)

                    # 查找提交按钮
                    submit_btn = await page.evaluate("""() => {
                        const btns = Array.from(document.querySelectorAll('button')).filter(b => b.offsetParent !== null);
                        return btns.map(b => ({text: b.textContent.trim(), id: b.id, disabled: b.disabled}));
                    }""")
                    print(f"  按钮: {submit_btn}")

                    # 点击提交
                    await page.evaluate("""() => {
                        const btns = Array.from(document.querySelectorAll('button')).filter(b => b.offsetParent !== null);
                        const btn = btns.find(b => /verify|submit|confirm|continue|next|验证|确认/i.test(b.textContent));
                        if (btn) btn.click();
                    }""")

                    # 等待并抓包
                    print("  等待 OTP 提交请求 ...")
                    await page.wait_for_timeout(10000)

                    # 输出抓到的请求
                    print(f"\n  抓到 {len(captured_posts)} 个 POST 请求:")
                    for req in captured_posts:
                        if "datadoghq" not in req["url"]:
                            print(f"    POST {req['url'][:100]}")
                            if req["post_data"]:
                                print(f"      body: {req['post_data'][:200]}")
                            if req["auth"]:
                                print(f"      auth: Bearer {req['auth'][7:30]}...")

                break

        except Exception as e:
            print(f"  ❌ 访问失败: {e}")

    await browser.close()

    print(f"\n{'='*60}")
    print("完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_verify_page())
