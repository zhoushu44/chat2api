"""NVIDIA Build HTTP 注册测试脚本（完整流程）。

用法：
  python -m projects.nvidia_build.test_http_register_full

注意：
  - 需要先 pip install curl_cffi
  - 需要配置好邮箱 Provider 和 hCaptcha Provider
  - 此为完整流程测试，包含所有步骤
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
    # 配置（从 data/config.json 读取）
    config_path = root_dir / "data" / "config.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    else:
        config = {}
        print("⚠️ 未找到 data/config.json，使用默认配置")

    # 邮箱配置
    email_domain = config.get("email", {}).get("tempmail", {}).get("domain", "zhoushu.kdns.fr")
    
    # 生成测试邮箱
    import random
    test_email = f"{''.join(str(random.randint(0, 9)) for _ in range(8))}@{email_domain}"
    test_password = "zs1236547."

    print("=" * 60)
    print(f"测试邮箱：{test_email}")
    print(f"测试密码：{test_password}")
    print("=" * 60)

    # 代理配置
    proxy_info = None
    proxy_cfg = config.get("proxy", {}).get("socks5", {})
    if proxy_cfg.get("server"):
        proxy_info = type("ProxyInfo", (), {
            "server": proxy_cfg["server"],
            "username": proxy_cfg.get("username", ""),
            "password": proxy_cfg.get("password", "")
        })()
        print(f"代理：{proxy_info.server}")
    else:
        print("代理：直连")

    print("=" * 60)
    print("开始 HTTP 注册流程测试...")
    print("=" * 60)

    # 模拟真实的 ctx.email 和 ctx.captcha
    # 注意：这里需要根据你实际使用的邮箱/验证码服务来修改
    
    # 方案 1: 使用现有的 Provider（推荐）
    # 需要从 core.models 导入 RunContext 并构造一个 mock context
    try:
        from core.models import RunContext
        
        # 构造一个简化的 RunContext
        class MockEmailProvider:
            async def wait_code(self, email: str, timeout: float = 120):
                # 实际调用邮箱 Provider
                # 这里需要根据你的邮箱服务实现
                print(f"[邮箱 Provider] 等待验证码 {email}（{timeout}s）...")
                # 示例：如果是 Cloudflare Worker 邮箱
                if "cloudflare" in str(config.get("email", {})):
                    # 调用实际的 Cloudflare Worker API
                    pass
                # 等待用户手动输入验证码（测试用）
                await asyncio.sleep(timeout - 10)
                code = input("请输入邮箱验证码：")
                return code
        
        class MockCaptchaProvider:
            async def solve(self, sitekey: str, page_url: str, timeout: float = 180, **kwargs):
                # 实际调用验证码 Provider
                print(f"[验证码 Provider] 解 hCaptcha sitekey={sitekey[:20]}...")
                # 示例：使用 CaptchaRun
                if "captcharun" in str(config.get("captcha", {})):
                    # 调用实际的 CaptchaRun API
                    pass
                # 返回测试 token
                await asyncio.sleep(5)
                return "test_hcaptcha_token_" + "x" * 200
        
        mock_email = MockEmailProvider()
        mock_captcha = MockCaptchaProvider()
        
    except Exception as e:
        print(f"⚠️ Provider 导入失败：{e}")
        print("使用简化 mock 实现...")
        
        class SimpleMockEmail:
            async def wait_code(self, email: str, timeout: float = 120):
                print(f"[Mock] 等待验证码 {email}（{timeout}s）...")
                await asyncio.sleep(timeout - 10)
                return "123456"
        
        class SimpleMockCaptcha:
            async def solve(self, sitekey: str, page_url: str, timeout: float = 180, **kwargs):
                print(f"[Mock] 解 hCaptcha sitekey={sitekey[:20]}...")
                await asyncio.sleep(5)
                return "test_hcaptcha_token_" + "x" * 200
        
        mock_email = SimpleMockEmail()
        mock_captcha = SimpleMockCaptcha()

    # 执行注册
    try:
        result = await register_http(
            email=test_email,
            password=test_password,
            wait_code=lambda addr, timeout: mock_email.wait_code(addr, timeout),
            solve_captcha=lambda **kw: mock_captcha.solve(**kw),
            proxy_info=proxy_info,
            mail_timeout=120,
            captcha_timeout=180,
            log=lambda msg: print(f"[LOG] {msg}"),
        )

        print("\n" + "=" * 60)
        print("注册结果:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print("=" * 60)

        if result.get("apikey"):
            print("\n✅ 成功获取 API Key")
            print(f"API Key: {result['apikey'][:20]}...")
        elif result.get("error"):
            print(f"\n❌ 注册失败：{result['error']}")
        else:
            print("\n❓ 未知状态")

    except Exception as exc:
        print(f"\n❌ 异常：{exc}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
