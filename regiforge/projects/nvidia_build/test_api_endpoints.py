"""在浏览器中用 fetch 测试各种创建账户 API 端点

由于在浏览器中执行，Cookie 和 Authorization 会自动带上
"""
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))


async def test_api_endpoints():
    """在浏览器中测试 API 端点"""
    print("=" * 60)
    print("NVIDIA - 在浏览器中测试 API 端点")
    print("=" * 60)

    from patchright.async_api import async_playwright
    import random

    test_email = f"{''.join(str(random.randint(0, 9)) for _ in range(8))}@zhoushu.kdns.fr"
    proxy_server = "http://127.0.0.1:7897"

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
                            print(f"  注册表单加载 ({i*0.5+0.5}s + {j+1}s)")
                            break
                    break

            # 提取 key
            parsed = urlparse(page.url)
            params = parse_qs(parsed.query)
            key = params.get("key", [None])[0]
            print(f"  key: {key[:30]}...")

            # 在浏览器中用 fetch 测试各种 API 端点
            print("\n[2] 在浏览器中用 fetch 测试 API 端点 ...")

            # 所有可能的创建账户端点
            endpoints = [
                "/api/1/frontend/oauth/account/create",
                "/api/1/frontend/oauth/account/register",
                "/api/1/frontend/oauth/account/signup",
                "/api/1/frontend/oauth/account/submit",
                "/api/1/frontend/oauth/register",
                "/api/1/frontend/oauth/signup",
                "/api/1/frontend/oauth/create",
                "/api/1/frontend/oauth/submit",
                "/api/1/frontend/oauth/account",
                "/api/1/frontend/oauth/accounts/create",
                "/api/1/frontend/oauth/user/create",
                "/api/1/frontend/oauth/user/register",
                "/api/1/register",
                "/api/1/signup",
                "/api/1/account/create",
                "/api/1/account/register",
                "/api/1/create-account",
                "/api/1/frontend/oauth/account/validate",
                "/api/1/frontend/oauth/account/save",
                "/api/1/frontend/oauth/account/complete",
            ]

            results = await page.evaluate("""async (endpoints) => {
                const results = [];
                for (const ep of endpoints) {
                    try {
                        const resp = await fetch(`https://accounts.nvgs.nvidia.com${ep}`, {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                            },
                            body: JSON.stringify({test: true}),
                        });
                        const text = await resp.text();
                        results.push({
                            endpoint: ep,
                            status: resp.status,
                            body: text.substring(0, 150),
                        });
                    } catch (e) {
                        results.push({
                            endpoint: ep,
                            status: -1,
                            body: e.message.substring(0, 100),
                        });
                    }
                }
                return results;
            }""", endpoints)

            print(f"\n{'端点':<55} {'状态':>4} {'响应'}")
            print("-" * 100)
            for r in results:
                status = r["status"]
                marker = "✅" if status not in (404, -1) else "  "
                print(f"{marker} {r['endpoint']:<53} {status:>4} {r['body'][:60]}")

            # 找到非 404 的端点
            print("\n=== 非 404 的端点 ===")
            for r in results:
                if r["status"] != 404 and r["status"] != -1:
                    print(f"  ✅ {r['endpoint']} → HTTP {r['status']} {r['body'][:100]}")

        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(test_api_endpoints())
