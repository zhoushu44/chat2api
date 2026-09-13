"""NVIDIA 混合引擎 - L1 验收测试

测试 patchright + curl_cffi 混合模式
"""
import asyncio
import json
import sys
from pathlib import Path

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))

from projects.nvidia_build.steps._hybrid_engine import register_hybrid


async def test_l1_hybrid():
    """L1 验收: 混合模式单账号注册"""
    print("=" * 60)
    print("NVIDIA 混合模式 - L1 验收测试")
    print("=" * 60)

    # 加载配置
    config_path = root_dir / "data" / "config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    # 生成测试邮箱
    import random
    test_email = f"{''.join(str(random.randint(0, 9)) for _ in range(8))}@zhoushu.kdns.fr"
    test_password = "zs1236547."
    proxy_server = "http://127.0.0.1:7897"

    print(f"\n📧 邮箱: {test_email}")
    print(f"🔑 密码: {test_password}")
    print(f"📡 代理: {proxy_server}")
    print(f"🔧 模式: patchright + curl_cffi")
    print("=" * 60)

    # hCaptcha solver（使用 CaptchaRun）
    async def solve_captcha(sitekey: str, page_url: str) -> str:
        print(f"\n[验证码] sitekey={sitekey}")
        print(f"[验证码] page_url={page_url[:60]}")
        from captcha.hcaptcha.captcharun.provider import CaptchaRunHCaptchaProvider
        provider = CaptchaRunHCaptchaProvider()
        hc_config = config.get("captcha", {}).get("hcaptcha", {}).get("captcharun", {})
        provider.configure(hc_config)
        token = await provider.solve(sitekey=sitekey, page_url=page_url)
        print(f"[验证码] token={token[:30] if token else 'None'}...")
        return token or ""

    # 邮箱验证码
    async def wait_code(email: str, timeout: int = 120) -> str:
        print(f"\n[邮箱] 等待验证码: {email}")
        print("💡 请查看邮箱并输入验证码:")
        code = input(f"验证码: ").strip()
        return code

    # 运行混合注册
    result = await register_hybrid(
        email=test_email,
        password=test_password,
        proxy_server=proxy_server,
        headless=False,
        solve_captcha_fn=solve_captcha,
        wait_code_fn=wait_code,
        log=print,
    )

    print("\n" + "=" * 60)
    if result:
        print(f"✅ 注册结果:")
        print(f"  邮箱: {result.get('email')}")
        print(f"  API Key: {result.get('apikey', 'N/A')}")
        print(f"  状态: {result.get('status', 'unknown')}")
    else:
        print("❌ 注册失败")
    print("=" * 60)

    return result is not None


if __name__ == "__main__":
    success = asyncio.run(test_l1_hybrid())
    sys.exit(0 if success else 1)
