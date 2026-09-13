"""NVIDIA 抓包 v3 - 解 hCaptcha + 注入 + 点创建账户 + 抓 API

流程:
1. patchright 过 CF + 填邮箱 + 点 Next
2. 填密码 + 勾选条款
3. 用 CaptchaRun 解 hCaptcha（sitekey=3443d8f6-da7a-4326-929f-4d7fc89ab0d1）
4. 注入 hCaptcha token 到页面
5. 点"创建账户"按钮
6. 抓取创建账户的 API 请求
"""
import asyncio
import json
import sys
from pathlib import Path

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))


async def capture_register_api_v3():
    """解 hCaptcha + 注入 + 抓创建账户 API"""
    print("=" * 60)
    print("NVIDIA 抓包 v3 - 解 hCaptcha + 创建账户 API")
    print("=" * 60)

    from patchright.async_api import async_playwright
    import random

    test_email = f"{''.join(str(random.randint(0, 9)) for _ in range(8))}@zhoushu.kdns.fr"
    test_password = "zs1236547."
    proxy_server = "http://127.0.0.1:7897"
    HCAPTCHA_SITEKEY = "3443d8f6-da7a-4326-929f-4d7fc89ab0d1"

    print(f"\n📧 邮箱: {test_email}")
    print(f"🔑 sitekey: {HCAPTCHA_SITEKEY}")
    print("=" * 60)

    captured_posts = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, proxy={"server": proxy_server})
        context = await browser.new_context()
        page = await context.new_page()

        def on_request(request):
            if request.method != "POST":
                return
            if any(x in request.url for x in ["datadoghq", "analytics", "client-logger", "akam", "awswaf"]):
                return
            entry = {
                "url": request.url,
                "post_data": request.post_data,
                "auth": request.headers.get("authorization", ""),
            }
            captured_posts.append(entry)
            print(f"\n  >>> POST {request.url[:100]}")
            if request.post_data:
                print(f"      body: {request.post_data[:200]}")

        page.on("request", on_request)

        try:
            # 1. 过 CF + 填邮箱 + 点 Next
            print("\n[1] 访问 build.nvidia.com ...")
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

            # 2. 等注册表单
            print("\n[2] 等注册表单 ...")
            for i in range(60):
                await page.wait_for_timeout(500)
                if "nvgs" in page.url:
                    for j in range(30):
                        await page.wait_for_timeout(1000)
                        if await page.locator("input[type='password']").count() > 0:
                            print(f"  表单加载 ({i*0.5+0.5}s + {j+1}s)")
                            break
                    break

            # 3. 填密码（等所有密码框渲染完）
            print(f"\n[3] 填密码 ...")
            await page.wait_for_timeout(2000)  # 等确认密码框渲染
            pwd_inputs = page.locator("input[type='password']")
            pwd_count = await pwd_inputs.count()
            print(f"  密码框数量: {pwd_count}")
            for i in range(pwd_count):
                await pwd_inputs.nth(i).fill(test_password)
                print(f"  填密码框[{i}]")

            # 4. 勾选条款
            print(f"\n[4] 勾选条款 ...")
            checkboxes = page.locator("input[type='checkbox']")
            cb_count = await checkboxes.count()
            print(f"  checkbox 数量: {cb_count}")
            for i in range(cb_count):
                checked = await checkboxes.nth(i).is_checked()
                if not checked:
                    await page.evaluate(f"""() => {{
                        const cbs = document.querySelectorAll('input[type="checkbox"]');
                        if (cbs[{i}]) cbs[{i}].click();
                    }}""")
                    print(f"  点击 checkbox[{i}]")
                await page.wait_for_timeout(500)

            # 5. 解 hCaptcha
            print(f"\n[5] 用 CaptchaRun 解 hCaptcha ...")
            hcaptcha_token = ""
            try:
                from captcha.hcaptcha.captcharun.provider import CaptchaRunHCaptchaProvider
                config = json.load(open(root_dir / "data" / "config.json", "r", encoding="utf-8"))
                hc_config = config.get("captcha", {}).get("hcaptcha", {}).get("captcharun", {})
                provider = CaptchaRunHCaptchaProvider()
                provider.configure(hc_config)
                hcaptcha_token = await provider.solve(
                    sitekey=HCAPTCHA_SITEKEY,
                    page_url=page.url,
                )
                print(f"  hCaptcha token: {hcaptcha_token[:40] if hcaptcha_token else 'None'}...")
            except Exception as e:
                print(f"  ❌ hCaptcha 失败: {e}")

            if not hcaptcha_token:
                print("\n❌ 无法获取 hCaptcha token，无法继续")
                await page.screenshot(path="data/debug/nvidia_build/no_hcaptcha_token.png")
                return

            # 6. 注入 hCaptcha token
            print(f"\n[6] 注入 hCaptcha token 到页面 ...")
            injected = await page.evaluate("""(token) => {
                let ok = false;

                // 1. 设置 h-captcha-response textarea/input
                const inputs = document.querySelectorAll('[name="h-captcha-response"], textarea[name="h-captcha-response"]');
                inputs.forEach(input => {
                    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set
                        || Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
                    if (setter) setter.call(input, token); else input.value = token;
                    input.dispatchEvent(new Event('input', {bubbles: true}));
                    input.dispatchEvent(new Event('change', {bubbles: true}));
                    ok = true;
                });

                // 2. 触发 hcaptcha 回调
                if (window.hcaptcha) {
                    try {
                        // 查找所有 hcaptcha widget
                        const widgets = document.querySelectorAll('[data-hcaptcha-widget-id], .h-captcha');
                        widgets.forEach(w => {
                            const widgetId = w.dataset.hcaptchaWidgetId || w.dataset.widgetId;
                            if (widgetId && window.hcaptcha.execute) {
                                try { window.hcaptcha.execute(widgetId); } catch {}
                            }
                        });
                    } catch {}
                }

                // 3. 触发全局回调
                const callbacks = ['onCaptchaSuccess', 'onHCaptchaSuccess', 'hcaptchaCallback', 'onCaptchaVerified'];
                callbacks.forEach(cb => {
                    if (typeof window[cb] === 'function') {
                        try { window[cb](token); ok = true; } catch {}
                    }
                });

                // 4. 查找 data-callback 属性
                const cbElements = document.querySelectorAll('[data-callback]');
                cbElements.forEach(el => {
                    const cbName = el.dataset.callback;
                    if (cbName && typeof window[cbName] === 'function') {
                        try { window[cbName](token); ok = true; } catch {}
                    }
                });

                return ok;
            }""", hcaptcha_token)
            print(f"  注入结果: {injected}")

            # 7. 等按钮启用 + 点击
            print(f"\n[7] 等待创建账户按钮启用 ...")
            for i in range(15):
                await page.wait_for_timeout(1000)
                disabled = await page.evaluate("""() => {
                    const btn = document.getElementById('register_button');
                    return btn ? btn.disabled : true;
                }""")
                if not disabled:
                    print(f"  按钮已启用 ({i+1}s)")
                    break
                if i % 3 == 0:
                    print(f"  [{i+1}s] 按钮仍 disabled")

            # 检查按钮状态
            btn_disabled = await page.evaluate("""() => {
                const btn = document.getElementById('register_button');
                return btn ? btn.disabled : true;
            }""")

            if btn_disabled:
                print(f"  ⚠️ 按钮仍 disabled，尝试强制点击 ...")
                # 强制点击（即使 disabled）
                await page.evaluate("""() => {
                    const btn = document.getElementById('register_button');
                    if (btn) {
                        btn.disabled = false;
                        btn.click();
                    }
                }""")
            else:
                print(f"  点击创建账户 ...")
                await page.evaluate("""() => {
                    const btn = document.getElementById('register_button');
                    if (btn) btn.click();
                }""")

            # 8. 等待 API 响应
            print(f"\n[8] 等待 API 响应（最多 30s）...")
            for i in range(30):
                await page.wait_for_timeout(1000)
                url = page.url
                if "profile-complete" in url or "verify" in url or "otp" in url:
                    print(f"  ✅ 跳转到: {url[:80]}")
                    break
                if i % 5 == 0:
                    print(f"  [{i+1}s] URL: {url[:80]}")

            await page.wait_for_timeout(5000)

        finally:
            await browser.close()

    # 输出结果
    print(f"\n{'='*60}")
    print(f"捕获到 {len(captured_posts)} 个业务 POST 请求:")
    print(f"{'='*60}")
    for entry in captured_posts:
        print(f"\nPOST {entry['url']}")
        if entry.get("auth"):
            print(f"  auth: Bearer {entry['auth'][7:30]}...")
        if entry["post_data"]:
            print(f"  body: {entry['post_data'][:300]}")

    output = root_dir / "data" / "debug" / "nvidia_build" / "captured_register_api_v3.json"
    with open(output, "w", encoding="utf-8") as f:
        json.dump(captured_posts, f, indent=2, ensure_ascii=False)
    print(f"\n💾 已保存: {output}")


if __name__ == "__main__":
    asyncio.run(capture_register_api_v3())
