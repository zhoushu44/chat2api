"""测试 patchright（反检测 Playwright）能否绕过 build.nvidia.com 的 Cloudflare 202"""
import asyncio
import sys
from pathlib import Path

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))


async def test_patchright_cf():
    """用 patchright 访问 build.nvidia.com，看能否过 CF"""
    print("=" * 60)
    print("patchright 反检测浏览器 - NVIDIA CF 测试")
    print("=" * 60)

    # 用 patchright 替代 playwright
    from patchright.async_api import async_playwright

    # 用本地 Clash 代理（无需认证）
    proxy_server = "http://127.0.0.1:7897"

    print(f"\n🌐 目标: https://build.nvidia.com/?modal=signin")
    print(f"📡 代理: {proxy_server}")
    print(f"🔧 浏览器: patchright (反检测 Playwright)")
    print("=" * 60)

    async with async_playwright() as p:
        # 启动浏览器（有头模式，方便观察）
        browser = await p.chromium.launch(
            headless=False,
            proxy={"server": proxy_server},
        )
        context = await browser.new_context()
        page = await context.new_page()

        try:
            print("\n[1] 访问 build.nvidia.com/?modal=signin ...")
            response = await page.goto(
                "https://build.nvidia.com/?modal=signin",
                wait_until="domcontentloaded",
                timeout=60000,
            )

            status = response.status if response else "?"
            url = page.url
            title = await page.title()

            print(f"  HTTP {status}")
            print(f"  URL: {url}")
            print(f"  Title: {title}")

            # 等待 CF 挑战通过 + signin 模态框加载
            print("\n[2] 等待 CF 挑战 + signin 模态框加载（最多 60s）...")
            email_found = False
            for i in range(60):
                await page.wait_for_timeout(1000)
                url = page.url
                title = await page.title()
                email_input = await page.locator("input[name='email'], input[type='email']").count()
                if email_input > 0:
                    print(f"  [{i+1}s] ✅ 邮箱输入框已出现！Title={title}")
                    email_found = True
                    break
                if i % 5 == 0:
                    print(f"  [{i+1}s] Title={title}, email_inputs={email_input}")

            # 检查是否到了 signin 页
            print("\n[3] 检查页面状态...")
            url = page.url
            title = await page.title()

            # 检查邮箱输入框是否存在
            email_input = await page.locator("input[name='email'], input[type='email']").count()
            print(f"  URL: {url}")
            print(f"  Title: {title}")
            print(f"  邮箱输入框数量: {email_input}")

            if email_found or email_input > 0:
                print("\n✅ patchright 成功绕过 CF！signin 页已加载")

                # 提取页面 HTML 中的 key
                html = await page.content()
                print(f"  HTML 长度: {len(html)}")

                import re
                key = None
                patterns = [
                    r'"key"\s*:\s*"([a-f0-9-]+)"',
                    r'key\s*:\s*"([a-f0-9-]+)"',
                    r'<meta[^>]+name=["\']?key["\']?[^>]+content=["\']([^"\']+)["\']',
                    r'data-key=["\']([^"\']+)["\']',
                ]
                for pattern in patterns:
                    match = re.search(pattern, html, re.IGNORECASE)
                    if match:
                        key = match.group(1)
                        print(f"\n✅ 提取到 key: {key[:30]}...")
                        break

                if not key:
                    print("\n⚠️  未找到 key（可能需要填邮箱点 Next 后才生成）")

                # 获取 Cookie
                cookies = await context.cookies()
                print(f"\n✅ 获取到 {len(cookies)} 个 Cookie")
                cf_clearance = None
                for c in cookies:
                    if c["name"] == "cf_clearance":
                        cf_clearance = c["value"]
                        print(f"  cf_clearance: {cf_clearance[:30]}...")

                print("\n💡 结论：patchright 可以绕过 NVIDIA 的 CF 202！")
                print("💡 后续可用 cf_clearance + Cookie 切换到 curl_cffi 完成 HTTP 注册")

                return True
            else:
                print("\n❌ signin 页未加载（邮箱输入框不存在）")
                # 保存截图
                await page.screenshot(path="data/debug/nvidia_patchright_fail.png")
                print("💾 截图: data/debug/nvidia_patchright_fail.png")
                return False

        except Exception as e:
            print(f"\n❌ 异常: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            await browser.close()


if __name__ == "__main__":
    success = asyncio.run(test_patchright_cf())
    sys.exit(0 if success else 1)
