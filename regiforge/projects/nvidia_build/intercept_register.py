"""NVIDIA - 拦截 XHR 获取 user/register 的正确字段名

通过注入 XHR 拦截脚本，在浏览器中提交表单时记录请求体
"""
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))


async def intercept_register_request():
    """拦截 XHR 获取正确字段"""
    print("=" * 60)
    print("NVIDIA - 拦截 XHR 获取 user/register 字段")
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

        # 注入 XHR 拦截脚本（在页面加载前）
        await page.add_init_script("""() => {
            window.__captured_requests = [];

            // 拦截 fetch
            const origFetch = window.fetch;
            window.fetch = async function(...args) {
                const [url, options] = args;
                const urlStr = typeof url === 'string' ? url : url.url;
                if (urlStr && urlStr.includes('user/register')) {
                    window.__captured_requests.push({
                        type: 'fetch',
                        url: urlStr,
                        method: options?.method || 'GET',
                        body: options?.body || null,
                        headers: options?.headers || {},
                    });
                    console.log('INTERCEPTED fetch user/register:', options?.body);
                }
                return origFetch.apply(this, args);
            };

            // 拦截 XMLHttpRequest
            const origOpen = XMLHttpRequest.prototype.open;
            const origSend = XMLHttpRequest.prototype.send;
            XMLHttpRequest.prototype.open = function(method, url, ...rest) {
                this.__url = url;
                this.__method = method;
                return origOpen.call(this, method, url, ...rest);
            };
            XMLHttpRequest.prototype.send = function(body) {
                if (this.__url && this.__url.includes('user/register')) {
                    window.__captured_requests.push({
                        type: 'xhr',
                        url: this.__url,
                        method: this.__method,
                        body: body,
                    });
                    console.log('INTERCEPTED XHR user/register:', body);
                }
                return origSend.call(this, body);
            };
        }""")

        try:
            # 1. 过 CF + 填邮箱 + 点 Next
            print("\n[1] 过 CF + 填邮箱 ...")
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
                            print(f"  表单加载 ({i*0.5+0.5}s + {j+1}s)")
                            break
                    break

            # 2. 填密码 + 勾选
            print(f"\n[2] 填密码 + 勾选 ...")
            await page.wait_for_timeout(2000)
            pwd_inputs = page.locator("input[type='password']")
            for i in range(await pwd_inputs.count()):
                await pwd_inputs.nth(i).fill(test_password)

            checkboxes = page.locator("input[type='checkbox']")
            for i in range(await checkboxes.count()):
                if not await checkboxes.nth(i).is_checked():
                    await page.evaluate(f"""() => {{
                        const cbs = document.querySelectorAll('input[type="checkbox"]');
                        if (cbs[{i}]) cbs[{i}].click();
                    }}""")
                    await page.wait_for_timeout(500)

            # 3. 解 hCaptcha + 注入
            print(f"\n[3] 解 hCaptcha + 注入 ...")
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

            if hcaptcha_token:
                # 注入 token + 触发 Angular change detection
                print(f"\n[4] 注入 hCaptcha token + 触发 Angular ...")
                injected = await page.evaluate("""(token) => {
                    // 1. 设置 h-captcha-response
                    const inputs = document.querySelectorAll('[name="h-captcha-response"], textarea[name="h-captcha-response"]');
                    inputs.forEach(input => {
                        const setter = Object.getOwnPropertyDescriptor(
                            input.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype,
                            'value'
                        )?.set;
                        if (setter) setter.call(input, token); else input.value = token;
                        input.dispatchEvent(new Event('input', {bubbles: true}));
                        input.dispatchEvent(new Event('change', {bubbles: true}));
                    });

                    // 2. 尝试调用 hcaptcha 回调
                    if (window.hcaptcha) {
                        // 查找 widget
                        const widgets = document.querySelectorAll('[data-hcaptcha-widget-id], .h-captcha, [data-sitekey]');
                        widgets.forEach(w => {
                            const id = w.dataset.hcaptchaWidgetId;
                            if (id) {
                                try {
                                    // 设置 response
                                    if (window.hcaptcha.setValue) {
                                        window.hcaptcha.setValue(id, token);
                                    }
                                } catch {}
                            }
                        });
                    }

                    // 3. 查找并触发 data-callback
                    const cbElements = document.querySelectorAll('[data-callback]');
                    let callbackResult = [];
                    cbElements.forEach(el => {
                        const cbName = el.dataset.callback;
                        if (cbName && typeof window[cbName] === 'function') {
                            try {
                                window[cbName](token);
                                callbackResult.push(cbName);
                            } catch (e) {
                                callbackResult.push(cbName + ':ERROR:' + e.message);
                            }
                        }
                    });

                    // 4. 触发 Angular change detection
                    // 尝试通过 ngZone
                    const appRef = window.ng?.getAppRef?.();
                    if (appRef) {
                        try { appRef.tick(); } catch {}
                    }

                    // 5. 查找 Angular 组件
                    const createAccountEl = document.querySelector('create-account');
                    if (createAccountEl) {
                        // 尝试获取 Angular 组件实例
                        const ngComponent = window.ng?.getComponent?.(createAccountEl);
                        if (ngComponent) {
                            // 尝试设置 form value
                            if (ngComponent.form) {
                                try {
                                    ngComponent.form.patchValue({
                                        'hCaptchaResponse': token,
                                        'h-captcha-response': token,
                                    });
                                    callbackResult.push('form.patchValue:OK');
                                } catch (e) {
                                    callbackResult.push('form.patchValue:ERROR:' + e.message);
                                }
                            }
                        }
                    }

                    return {
                        inputsFound: inputs.length,
                        callbacks: callbackResult,
                        hasHcaptcha: !!window.hcaptcha,
                        hasNg: !!window.ng,
                    };
                }""", hcaptcha_token)
                print(f"  注入结果: {json.dumps(injected, indent=2)}")

                # 5. 检查按钮状态 + 强制启用
                print(f"\n[5] 检查按钮状态 ...")
                btn_state = await page.evaluate("""() => {
                    const btn = document.getElementById('register_button');
                    if (!btn) return {found: false};
                    return {
                        found: true,
                        disabled: btn.disabled,
                        className: btn.className,
                    };
                }""")
                print(f"  按钮状态: {btn_state}")

                # 强制启用 + 点击
                print(f"\n[6] 强制启用 + 点击按钮 ...")
                await page.evaluate("""() => {
                    const btn = document.getElementById('register_button');
                    if (btn) {
                        btn.disabled = false;
                        btn.removeAttribute('disabled');
                    }
                }""")

                # 用 Playwright 点击（真实鼠标事件）
                try:
                    await page.locator("#register_button").click(timeout=5000)
                    print(f"  点击成功")
                except Exception as e:
                    print(f"  点击失败: {e}")
                    # 用 JS 点击
                    await page.evaluate("""() => {
                        const btn = document.getElementById('register_button');
                        if (btn) {
                            btn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
                        }
                    }""")
                    print(f"  JS 点击")

                # 6. 等待并检查拦截的请求
                print(f"\n[7] 检查拦截的请求 ...")
                await page.wait_for_timeout(5000)

                captured = await page.evaluate("""() => window.__captured_requests || []""")
                print(f"  拦截到 {len(captured)} 个 user/register 请求")
                for req in captured:
                    print(f"\n  {'='*50}")
                    print(f"  type: {req['type']}")
                    print(f"  url: {req['url'][:100]}")
                    print(f"  method: {req['method']}")
                    if req.get("body"):
                        body = req["body"]
                        if isinstance(body, str):
                            print(f"  body: {body[:500]}")
                            # 尝试解析 JSON
                            try:
                                parsed = json.loads(body)
                                print(f"  parsed: {json.dumps(parsed, indent=2)[:500]}")
                            except:
                                pass
                        else:
                            print(f"  body: {str(body)[:500]}")
                    if req.get("headers"):
                        print(f"  headers: {json.dumps(req['headers'], indent=2)[:200]}")

                if not captured:
                    print("  ⚠️ 未拦截到 user/register 请求")
                    print("  检查是否有其他 API 请求...")
                    # 检查 Angular 是否有错误
                    console_logs = await page.evaluate("""() => {
                        return document.querySelectorAll('.error, .alert, [class*="error"]').length;
                    }""")
                    print(f"  页面错误元素数量: {console_logs}")

                    # 截图
                    await page.screenshot(path="data/debug/nvidia_build/register_intercept.png")
                    print(f"  截图: data/debug/nvidia_build/register_intercept.png")

        finally:
            await browser.close()

    print(f"\n{'='*60}")
    print("完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(intercept_register_request())
