"""NVIDIA 网络请求抓包 - 用 patchright 监控注册流程的所有 API 请求

目的：找到表单提交的实际 API 端点（不是页面 URL）
"""
import asyncio
import json
import sys
from pathlib import Path

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))


async def capture_network():
    """用 patchright 监控 NVIDIA 注册的网络请求"""
    print("=" * 60)
    print("NVIDIA 网络请求抓包 - 找到实际 API 端点")
    print("=" * 60)

    from patchright.async_api import async_playwright
    import random

    test_email = f"{''.join(str(random.randint(0, 9)) for _ in range(8))}@zhoushu.kdns.fr"
    test_password = "zs1236547."
    proxy_server = "http://127.0.0.1:7897"

    print(f"\n📧 邮箱: {test_email}")
    print("=" * 60)

    captured = []  # 保存所有网络请求

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            proxy={"server": proxy_server},
        )
        context = await browser.new_context()
        page = await context.new_page()

        # 监控所有请求
        def on_request(request):
            # 只记录 API 请求（非静态资源）
            url = request.url
            if any(url.endswith(ext) for ext in [".js", ".css", ".png", ".jpg", ".svg", ".woff", ".ico"]):
                return
            if "analytics" in url or "tracking" in url:
                return

            entry = {
                "method": request.method,
                "url": url[:200],
                "headers": dict(request.headers),
                "post_data": request.post_data[:500] if request.post_data else None,
            }
            captured.append(entry)
            if request.method in ("POST", "PUT", "PATCH"):
                print(f"\n  >>> {request.method} {url[:100]}")
                if request.post_data:
                    print(f"      body: {request.post_data[:200]}")

        page.on("request", on_request)

        try:
            # 1. 访问 build.nvidia.com
            print("\n[1] 访问 build.nvidia.com ...")
            await page.goto("https://build.nvidia.com/?modal=signin", wait_until="domcontentloaded", timeout=60000)

            # 等邮箱输入框
            for i in range(60):
                await page.wait_for_timeout(1000)
                if await page.locator("input[name='email'], input[type='email']").count() > 0:
                    print(f"  CF 过了 ({i+1}s)")
                    break

            # 2. 填邮箱 + 点 Next
            print(f"\n[2] 填邮箱 + 点 Next ...")
            email_loc = page.locator("input[name='email'], input[type='email']").first
            await email_loc.click(timeout=5000)
            await email_loc.fill(test_email)
            await page.wait_for_timeout(1000)

            await page.evaluate("""() => {
                const btns = Array.from(document.querySelectorAll('button')).filter(b => b.offsetParent !== null);
                let b = btns.find(b => b.textContent.trim() === 'Next');
                if (b) b.click();
            }""")

            # 3. 等跳转到 NVGS + 注册表单
            print("\n[3] 等待 NVGS 注册表单 ...")
            for i in range(60):
                await page.wait_for_timeout(500)
                url = page.url
                if "nvgs" in url or ("login" in url and "build.nvidia" not in url):
                    print(f"  跳转到 NVGS: {url[:80]}")
                    # 等密码输入框
                    for j in range(30):
                        await page.wait_for_timeout(1000)
                        if await page.locator("input[type='password']").count() > 0:
                            print(f"  注册表单加载 ({j+1}s)")
                            break
                    break

            # 4. 填密码
            print(f"\n[4] 填密码 ...")
            pwd_inputs = page.locator("input[type='password']")
            pwd_count = await pwd_inputs.count()
            print(f"  密码输入框数量: {pwd_count}")

            for i in range(pwd_count):
                loc = pwd_inputs.nth(i)
                name = await loc.get_attribute("name") or f"pwd_{i}"
                placeholder = await loc.get_attribute("placeholder") or ""
                print(f"  [{i}] name={name}, placeholder={placeholder}")

            # 填密码
            if pwd_count >= 1:
                await pwd_inputs.nth(0).fill(test_password)
                print(f"  已填密码到第 1 个框")
            if pwd_count >= 2:
                await pwd_inputs.nth(1).fill(test_password)
                print(f"  已填密码到第 2 个框（确认密码）")

            # 5. 勾选同意条款
            print(f"\n[5] 勾选同意条款 ...")
            checkboxes = page.locator("input[type='checkbox']")
            cb_count = await checkboxes.count()
            print(f"  checkbox 数量: {cb_count}")
            for i in range(cb_count):
                loc = checkboxes.nth(i)
                name = await loc.get_attribute("name") or f"cb_{i}"
                checked = await loc.is_checked()
                print(f"  [{i}] name={name}, checked={checked}")
                if not checked and "agreement" in (name or "").lower():
                    await loc.check()
                    print(f"  已勾选: {name}")

            # 6. 查找 hCaptcha
            print(f"\n[6] 查找 hCaptcha ...")
            hcaptcha_iframes = page.locator("iframe[src*='hcaptcha'], iframe[src*='captcha']")
            hc_count = await hcaptcha_iframes.count()
            print(f"  hCaptcha iframe 数量: {hc_count}")

            # 从页面源码找 sitekey
            html = await page.content()
            import re
            sitekey_patterns = [
                r'data-sitekey=["\']([^"\']+)["\']',
                r'hcaptcha[^"\'<>]*["\']([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})["\']',
                r'sitekey["\']?\s*[:=]\s*["\']([a-f0-9-]+)["\']',
            ]
            for pat in sitekey_patterns:
                m = re.search(pat, html, re.IGNORECASE)
                if m:
                    print(f"  ✅ sitekey: {m.group(1)}")
                    break
            else:
                print(f"  ⚠️ 未找到 sitekey")

            # 找 Register/Create Account 按钮
            print(f"\n[7] 查找注册按钮 ...")
            buttons = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('button'))
                    .filter(b => b.offsetParent !== null)
                    .map(b => ({text: b.textContent.trim().substring(0, 50), id: b.id, class: b.className.substring(0, 50)}));
            }""")
            for b in buttons:
                print(f"  按钮: text={b['text']}, id={b['id']}, class={b['class']}")

            # 7. 查找表单的 action 和 JS 中的 API 端点
            print(f"\n[8] 分析表单和 JS ...")
            forms = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('form')).map(f => ({
                    action: f.action,
                    method: f.method,
                    id: f.id,
                    inputs: Array.from(f.querySelectorAll('input')).map(i => ({name: i.name, type: i.type}))
                }));
            }""")
            for f in forms:
                print(f"  form: action={f['action']}, method={f['method']}, id={f['id']}")
                for inp in f['inputs']:
                    print(f"    input: name={inp['name']}, type={inp['type']}")

            # 从 JS 中找 API 端点
            js_apis = re.findall(r'["\'](https?://[^"\']*api[^"\']*|/v[0-9]/[^"\']*)["\']', html)
            if js_apis:
                print(f"\n  JS 中的 API 端点:")
                for api in set(js_apis[:20]):
                    print(f"    {api}")

            # 保存完整 HTML 供分析
            output_html = root_dir / "data" / "debug" / "nvidia_build" / "nvgs_register_page.html"
            output_html.parent.mkdir(parents=True, exist_ok=True)
            with open(output_html, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"\n  HTML 已保存: {output_html}")

            # 等待用户观察
            print(f"\n[9] 浏览器保持打开 30 秒供观察 ...")
            await page.wait_for_timeout(30000)

        finally:
            await browser.close()

    # 保存捕获的请求
    print(f"\n{'='*60}")
    print(f"捕获到 {len(captured)} 个网络请求")
    print(f"POST/PUT/PATCH 请求:")
    for entry in captured:
        if entry["method"] in ("POST", "PUT", "PATCH"):
            print(f"  {entry['method']} {entry['url'][:100]}")
            if entry["post_data"]:
                print(f"    body: {entry['post_data'][:200]}")

    output = root_dir / "data" / "debug" / "nvidia_build" / "captured_requests.json"
    with open(output, "w", encoding="utf-8") as f:
        json.dump(captured, f, indent=2, ensure_ascii=False)
    print(f"\n💾 所有请求已保存: {output}")


if __name__ == "__main__":
    asyncio.run(capture_network())
