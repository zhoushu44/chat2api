"""NVIDIA 混合模式 - patchright 过 CF + curl_cffi 后续

流程：
1. patchright 访问 build.nvidia.com（2 秒过 CF）
2. 填邮箱 → 点 Next → 跳转到 NVGS
3. 提取 key + Cookie + UA
4. 切 curl_cffi：用 key + Cookie 访问 NVGS 注册页
5. 验证 NVGS 注册页是否加载成功
"""
import asyncio
import json
import sys
from pathlib import Path

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))


async def test_hybrid_extract_key():
    """测试混合模式：patchright 提取 key + curl_cffi 访问 NVGS"""
    print("=" * 60)
    print("NVIDIA 混合模式 - patchright + curl_cffi")
    print("=" * 60)

    from patchright.async_api import async_playwright
    from curl_cffi import requests as cc_requests
    import random

    # 测试邮箱
    test_email = f"{''.join(str(random.randint(0, 9)) for _ in range(8))}@zhoushu.kdns.fr"
    proxy_server = "http://127.0.0.1:7897"

    print(f"\n📧 测试邮箱: {test_email}")
    print(f"📡 代理: {proxy_server}")
    print(f"🔧 浏览器: patchright (反检测)")
    print("=" * 60)

    extracted = {}  # 保存提取的信息

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            proxy={"server": proxy_server},
        )
        context = await browser.new_context()
        page = await context.new_page()

        try:
            # ── 步骤 1: 访问 build.nvidia.com ──
            print("\n[步骤 1] 访问 build.nvidia.com/?modal=signin ...")
            await page.goto(
                "https://build.nvidia.com/?modal=signin",
                wait_until="domcontentloaded",
                timeout=60000,
            )

            # 等邮箱输入框出现（CF 已过 + 模态框加载）
            print("[步骤 1] 等待 CF 通过 + signin 模态框加载...")
            for i in range(60):
                await page.wait_for_timeout(1000)
                email_input = await page.locator("input[name='email'], input[type='email']").count()
                if email_input > 0:
                    print(f"  [{i+1}s] ✅ 邮箱输入框已出现")
                    break
                if i % 5 == 0:
                    title = await page.title()
                    print(f"  [{i+1}s] 等待... Title={title}")
            else:
                print("  ❌ 60s 内邮箱输入框未出现")
                return False

            # ── 步骤 2: 填邮箱 + 点 Next ──
            print(f"\n[步骤 2] 填邮箱: {test_email}")
            email_loc = page.locator("input[name='email'], input[type='email']").first
            await email_loc.click(timeout=5000)
            await email_loc.fill(test_email)
            await page.wait_for_timeout(1000)

            # 点 Next 按钮
            print("[步骤 2] 点击 Next ...")
            clicked = await page.evaluate("""() => {
                const btns = Array.from(document.querySelectorAll('button'))
                    .filter(b => b.offsetParent !== null);
                let b = btns.find(b => b.textContent.trim() === 'Next');
                if (!b) b = btns.find(b => /next|continue/i.test(b.textContent) && b.className.includes('btn-primary'));
                if (b) { b.click(); return 'clicked: ' + b.textContent.trim(); }
                return 'no Next button found';
            }""")
            print(f"  结果: {clicked}")

            if not clicked.startswith("clicked"):
                print("  ❌ 未找到 Next 按钮")
                return False

            # ── 步骤 3: 等待跳转到 NVGS ──
            print("\n[步骤 3] 等待跳转到 NVGS (login.nvidia.com) ...")
            nvgs_url = None
            for i in range(60):
                await page.wait_for_timeout(500)
                url = page.url
                if "login.nvidia.com" in url or "nvgs" in url or "create-account" in url:
                    nvgs_url = url
                    print(f"  [{i*0.5+0.5}s] ✅ 已跳转到 NVGS: {url[:80]}")
                    break
                if i % 4 == 0:
                    print(f"  [{i*0.5+0.5}s] 当前 URL: {url[:80]}")

            if not nvgs_url:
                print(f"  ❌ 30s 内未跳转到 NVGS，当前 URL: {page.url}")
                await page.screenshot(path="data/debug/nvidia_hybrid_no_nvgs.png")
                return False

            # ── 步骤 4: 提取 key + Cookie ──
            print(f"\n[步骤 4] 提取 key 和 Cookie ...")
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(nvgs_url)
            params = parse_qs(parsed.query)
            key = params.get("key", [None])[0]

            if key:
                print(f"  ✅ key: {key[:30]}...")
            else:
                print(f"  ⚠️ URL 中无 key 参数，可能直接跳转")
                print(f"  完整 URL: {nvgs_url}")

            # 等待 NVGS 页面加载完成（密码输入框出现）
            print("[步骤 4] 等待 NVGS 注册表单加载...")
            for i in range(30):
                await page.wait_for_timeout(1000)
                pwd_input = await page.locator("input[name='registration_password'], input[type='password']").count()
                if pwd_input > 0:
                    print(f"  [{i+1}s] ✅ 注册表单已加载（密码输入框出现）")
                    break
                if i % 5 == 0:
                    print(f"  [{i+1}s] 等待... URL={page.url[:60]}")
            else:
                print(f"  ⚠️ 30s 内密码输入框未出现，继续提取 Cookie")

            # 提取 Cookie
            cookies = await context.cookies()
            cookie_dict = {c["name"]: c["value"] for c in cookies}
            print(f"  ✅ Cookie 数量: {len(cookie_dict)}")

            # 提取 UA
            ua = await page.evaluate("() => navigator.userAgent")
            print(f"  ✅ UA: {ua[:50]}...")

            # 提取当前页面 HTML
            html = await page.content()
            print(f"  ✅ HTML 长度: {len(html)}")

            # 检查 hCaptcha sitekey
            import re
            sitekey_match = re.search(r'data-sitekey=["\']([^"\']+)["\']', html)
            if sitekey_match:
                print(f"  ✅ hCaptcha sitekey: {sitekey_match.group(1)}")
            else:
                # 也从 script 标签找
                sitekey_match = re.search(r'sitekey["\']?\s*[:=]\s*["\']([a-f0-9-]+)["\']', html)
                if sitekey_match:
                    print(f"  ✅ hCaptcha sitekey: {sitekey_match.group(1)}")
                else:
                    print(f"  ⚠️ 未找到 hCaptcha sitekey")

            extracted = {
                "key": key,
                "cookies": cookie_dict,
                "ua": ua,
                "nvgs_url": nvgs_url,
                "email": test_email,
            }

        finally:
            await browser.close()

    # ── 步骤 5: 用 curl_cffi + Cookie 访问 NVGS ──
    print("\n[步骤 5] 切换到 curl_cffi，验证 Cookie 是否有效 ...")

    session = cc_requests.Session(impersonate="chrome145")
    session.proxies = {"http": proxy_server, "https": proxy_server}

    # 设置 Cookie
    for name, value in extracted["cookies"].items():
        session.cookies.set(name, value, domain=".nvidia.com")

    # 设置 UA
    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.9",
        "user-agent": extracted["ua"],
        "referer": "https://build.nvidia.com/",
    }

    # 访问 NVGS create-account
    test_url = extracted["nvgs_url"] or "https://login.nvidia.com/v1/create-account"
    print(f"  访问: {test_url[:80]}")
    response = session.get(test_url, headers=headers, allow_redirects=True, timeout=30)

    print(f"  HTTP {response.status_code}")
    print(f"  HTML 长度: {len(response.text)}")

    if response.status_code == 200:
        print("\n✅✅✅ curl_cffi 用 Cookie 成功访问 NVGS！")
        print("💡 混合模式可行！后续可用 curl_cffi 完成注册流程")

        # 保存提取的信息
        output_file = root_dir / "data" / "debug" / "nvidia_hybrid_extracted.json"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            # Cookie 太长，只保存摘要
            summary = {
                "key": extracted["key"],
                "cookie_count": len(extracted["cookies"]),
                "cookie_names": list(extracted["cookies"].keys()),
                "ua": extracted["ua"],
                "nvgs_url": extracted["nvgs_url"],
                "email": extracted["email"],
                "curl_cffi_status": response.status_code,
                "curl_cffi_html_len": len(response.text),
            }
            json.dump(summary, f, indent=2, ensure_ascii=False)
        print(f"💾 摘要已保存: {output_file}")

        return True
    else:
        print(f"\n❌ curl_cffi 访问 NVGS 失败: HTTP {response.status_code}")
        return False


if __name__ == "__main__":
    success = asyncio.run(test_hybrid_extract_key())
    print(f"\n{'='*60}")
    print(f"最终结果: {'✅ 成功' if success else '❌ 失败'}")
    print(f"{'='*60}")
    sys.exit(0 if success else 1)
