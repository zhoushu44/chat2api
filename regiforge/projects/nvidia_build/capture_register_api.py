"""NVIDIA 抓包 v2 - 完整注册流程，抓取创建账户的 API 端点

这次会：
1. patchright 过 CF + 填邮箱 + 点 Next
2. 填密码 + 勾选条款
3. 等待 hCaptcha 自动完成
4. 点"创建账户"按钮
5. 记录所有 POST 请求（特别是创建账户的 API）
"""
import asyncio
import json
import sys
from pathlib import Path

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))


async def capture_register_api():
    """完整注册流程抓包"""
    print("=" * 60)
    print("NVIDIA 抓包 v2 - 创建账户 API 端点")
    print("=" * 60)

    from patchright.async_api import async_playwright
    import random

    test_email = f"{''.join(str(random.randint(0, 9)) for _ in range(8))}@zhoushu.kdns.fr"
    test_password = "zs1236547."
    proxy_server = "http://127.0.0.1:7897"

    print(f"\n📧 邮箱: {test_email}")
    print("=" * 60)

    captured_posts = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, proxy={"server": proxy_server})
        context = await browser.new_context()
        page = await context.new_page()

        # 监控 POST 请求
        def on_request(request):
            if request.method != "POST":
                return
            if any(x in request.url for x in ["analytics", "tracking", "client-logger", "akam", "awswaf"]):
                return

            entry = {
                "url": request.url,
                "method": request.method,
                "post_data": request.post_data,
                "headers": {k: v for k, v in request.headers.items() if k in ("authorization", "content-type", "origin", "referer")},
            }
            captured_posts.append(entry)
            print(f"\n  >>> POST {request.url[:100]}")
            if request.post_data:
                print(f"      body: {request.post_data[:200]}")

        page.on("request", on_request)

        try:
            # 1. 访问 + 过 CF + 填邮箱 + 点 Next
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

            # 3. 填密码
            print(f"\n[3] 填密码 ...")
            pwd_inputs = page.locator("input[type='password']")
            pwd_count = await pwd_inputs.count()
            print(f"  密码框数量: {pwd_count}")
            for i in range(pwd_count):
                await pwd_inputs.nth(i).fill(test_password)
            print(f"  已填 {pwd_count} 个密码框")

            # 4. 勾选条款
            print(f"\n[4] 勾选条款 ...")
            checkboxes = page.locator("input[type='checkbox']")
            cb_count = await checkboxes.count()
            for i in range(cb_count):
                loc = checkboxes.nth(i)
                checked = await loc.is_checked()
                if not checked:
                    try:
                        await loc.check(timeout=2000)
                        print(f"  勾选 checkbox[{i}]")
                    except:
                        # 可能是 label 点击
                        await page.evaluate(f"""() => {{
                            const cbs = document.querySelectorAll('input[type="checkbox"]');
                            if (cbs[{i}]) cbs[{i}].click();
                        }}""")
                        print(f"  点击 checkbox[{i}]")

            # 5. 等 hCaptcha 自动完成
            print(f"\n[5] 等待 hCaptcha 自动完成（最多 60s）...")
            for i in range(60):
                await page.wait_for_timeout(1000)
                # 检查 hCaptcha 是否已通过
                hcaptcha_resp = await page.evaluate("""() => {
                    const input = document.querySelector('[name="h-captcha-response"], textarea[name="h-captcha-response"]');
                    return input ? input.value : null;
                }""")
                if hcaptcha_resp and len(hcaptcha_resp) > 10:
                    print(f"  hCaptcha 已通过 ({i+1}s): {hcaptcha_resp[:30]}...")
                    break
                # 检查是否有 hCaptcha 挑战弹窗
                hc_challenge = await page.locator("iframe[src*='hcaptcha']").count()
                if i % 5 == 0:
                    print(f"  [{i+1}s] hCaptcha iframe={hc_challenge}, resp={'有' if hcaptcha_resp else '无'}")

            # 6. 点"创建账户"按钮
            print(f"\n[6] 点'创建账户'按钮 ...")
            # 检查按钮是否可用
            btn_info = await page.evaluate("""() => {
                const btn = document.getElementById('register_button');
                if (btn) return {disabled: btn.disabled, text: btn.textContent.trim(), className: btn.className};
                return null;
            }""")
            print(f"  按钮状态: {btn_info}")

            if btn_info and not btn_info.get("disabled"):
                # 点击按钮
                await page.evaluate("""() => {
                    const btn = document.getElementById('register_button');
                    if (btn) btn.click();
                }""")
                print(f"  已点击创建账户")

                # 等待响应（最多 30 秒）
                print(f"\n[7] 等待 API 响应 ...")
                for i in range(30):
                    await page.wait_for_timeout(1000)
                    url = page.url
                    if "profile-complete" in url or "verify" in url or "otp" in url:
                        print(f"  ✅ 跳转到: {url[:80]}")
                        break
                    if i % 5 == 0:
                        print(f"  [{i+1}s] URL: {url[:80]}")
            else:
                print(f"  ❌ 按钮不可用或不存在")
                # 截图查看
                await page.screenshot(path="data/debug/nvidia_build/register_btn_disabled.png")
                print(f"  截图: data/debug/nvidia_build/register_btn_disabled.png")

            # 等一下让最后请求完成
            await page.wait_for_timeout(5000)

        finally:
            await browser.close()

    # 输出所有 POST 请求
    print(f"\n{'='*60}")
    print(f"捕获到 {len(captured_posts)} 个 POST 请求:")
    print(f"{'='*60}")
    for entry in captured_posts:
        print(f"\n{entry['method']} {entry['url']}")
        if entry.get("headers", {}).get("authorization"):
            print(f"  auth: Bearer {entry['headers']['authorization'][7:30]}...")
        if entry["post_data"]:
            print(f"  body: {entry['post_data'][:300]}")

    # 保存
    output = root_dir / "data" / "debug" / "nvidia_build" / "captured_register_api.json"
    with open(output, "w", encoding="utf-8") as f:
        json.dump(captured_posts, f, indent=2, ensure_ascii=False)
    print(f"\n💾 已保存: {output}")


if __name__ == "__main__":
    asyncio.run(capture_register_api())
