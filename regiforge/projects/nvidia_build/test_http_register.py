"""NVIDIA Build HTTP 注册测试脚本（单账号调试用）。

用法：
  python -m projects.nvidia_build.test_http_register

注意：
  - 需要先 pip install curl_cffi
  - 需要配置好邮箱 Provider 和 hCaptcha Provider
  - 建议先用 browser 模式跑通，再切 http 模式调试
"""
import asyncio
import json
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))

from projects.nvidia_build.steps._http_engine import register_http


async def main():
    # 配置（从 data/config.json 读取或手动指定）
    config_path = root_dir / "data" / "config.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    else:
        config = {}

    # 邮箱配置（示例：使用临时邮箱）
    email_domain = config.get("email", {}).get("tempmail", {}).get("domain", "zhoushu.kdns.fr")
    
    # 生成测试邮箱
    import random
    test_email = f"{''.join(str(random.randint(0, 9)) for _ in range(8))}@{email_domain}"
    test_password = "zs1236547."

    print(f"测试邮箱：{test_email}")
    print(f"测试密码：{test_password}")
    print("-" * 50)

    # 代理配置
    proxy_info = None
    proxy_cfg = config.get("proxy", {}).get("socks5", {})
    if proxy_cfg.get("server"):
        proxy_info = type("ProxyInfo", (), {"server": proxy_cfg["server"]})()
        print(f"代理：{proxy_info.server}")
    else:
        print("代理：直连")

    # 模拟 ctx.email 和 ctx.captcha
    class MockEmail:
        async def wait_code(self, email: str, timeout: float = 120):
            print(f"[MockEmail] 等待验证码 {email}（{timeout}s）...")
            # 实际使用时需要对接真实邮箱 Provider
            await asyncio.sleep(timeout - 10)
            return "123456"  # 测试用假码

    class MockCaptcha:
        async def solve(self, sitekey: str, page_url: str, timeout: float = 180, **kwargs):
            print(f"[MockCaptcha] 解 hCaptcha sitekey={sitekey[:20]}...")
            # 实际使用时需要对接真实验证码 Provider
            await asyncio.sleep(5)
            return "test_hcaptcha_token_" + "x" * 200

    # 执行注册
    try:
        result = await register_http(
            email=test_email,
            password=test_password,
            wait_code=lambda addr, timeout: MockEmail().wait_code(addr, timeout),
            solve_captcha=lambda **kw: MockCaptcha().solve(**kw),
            proxy_info=proxy_info,
            mail_timeout=120,
            captcha_timeout=180,
            log=lambda msg: print(f"[LOG] {msg}"),
        )

        print("\n" + "=" * 50)
        print("注册结果:")
        print(json.dumps(result, indent=2, ensure_ascii=False))

        if result.get("apikey"):
            print("\n✓ 成功获取 API Key")
        elif result.get("error"):
            print(f"\n✗ 注册失败：{result['error']}")
        else:
            print("\n? 未知状态")

    except Exception as exc:
        print(f"\n✗ 异常：{exc}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
