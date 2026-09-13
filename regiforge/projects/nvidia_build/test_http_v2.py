"""NVIDIA HTTP 模式 v2 - L1 验收测试

测试新的 HTTP 引擎，按照正确的流程：
1. 访问 build.nvidia.com 获取 key
2. 用 key 访问 NVGS
3. 提交注册表单
4. OTP 验证
5. 获取 API Key
"""
import asyncio
import json
import sys
from pathlib import Path

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))

from core.base import RunContext
from core.models import AccountResult
from projects.nvidia_build.steps._http_engine_v2 import NvHTTPClient


async def test_http_v2():
    """测试 HTTP 模式 v2"""
    print("=" * 60)
    print("NVIDIA HTTP 模式 v2 - L1 验收测试")
    print("=" * 60)
    
    # 加载配置
    config_path = root_dir / "data" / "config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    
    # 生成测试邮箱
    import random
    test_email = f"{''.join(str(random.randint(0, 9)) for _ in range(8))}@zhoushu.kdns.fr"
    test_password = "zs1236547."
    
    print(f"\n📧 测试邮箱：{test_email}")
    print(f"🔑 测试密码：{test_password}")
    print("=" * 60)
    
    # 创建 HTTP 客户端
    proxy_server = "socks5://sockstest:socks-pass%401@192.6.121.16:7890"
    client = NvHTTPClient(proxy=proxy_server)
    
    log_messages = []
    def log_fn(msg):
        print(f"[LOG] {msg}")
        log_messages.append(msg)
    
    print("\n🚀 开始 HTTP 模式 v2 测试...")
    print("=" * 60)
    
    try:
        # 步骤 1: 访问 build.nvidia.com 获取 key
        print("\n[步骤 1] 访问 build.nvidia.com 获取 key...")
        success, error = client.load_signup_page()
        if not success:
            print(f"❌ 步骤 1 失败：{error}")
            return False
        print(f"✅ 步骤 1 成功，key={client._key[:20] if client._key else 'None'}...")
        print(f"✅ Cookie 数量：{len(client._cookies)}")
        
        # 步骤 2: 提交邮箱，跳转到 NVGS
        print("\n[步骤 2] 提交邮箱，跳转到 NVGS...")
        success, error, redirect_url = client.submit_email(test_email)
        if not success:
            print(f"❌ 步骤 2 失败：{error}")
            return False
        print(f"✅ 步骤 2 成功，redirect_url={redirect_url}")
        
        # 步骤 3: 提交注册表单（需要 hCaptcha token）
        print("\n[步骤 3] 提交注册表单...")
        print("⚠️  需要 hCaptcha token，使用测试 token")
        hcaptcha_token = "test_token_" + "x" * 200
        success, error = client.submit_registration(test_email, test_password, hcaptcha_token)
        if not success:
            print(f"❌ 步骤 3 失败：{error}")
            return False
        print(f"✅ 步骤 3 成功")
        
        # 步骤 4: OTP 验证（需要手动输入）
        print("\n[步骤 4] OTP 验证...")
        print("💡 请在浏览器中查看邮箱验证码，然后输入：")
        try:
            code = input(f"验证码：")
        except:
            print("❌ 读取验证码失败")
            return False
        
        success, error = client.submit_otp(test_email, code)
        if not success:
            print(f"❌ 步骤 4 失败：{error}")
            return False
        print(f"✅ 步骤 4 成功")
        
        # 步骤 5-7: Post-Verification + API Key 获取
        # TODO: 需要实现后续步骤
        print("\n⚠️  后续步骤（Post-Verification + API Key）待实现")
        
        print("\n" + "=" * 60)
        print("✅ HTTP 模式 v2 框架测试通过！")
        print("📋 后续步骤需要实现：")
        print("  - handle_post_verification()")
        print("  - fetch_api_key()")
        print("=" * 60)
        
        return True
        
    except Exception as e:
        print(f"\n❌ 异常：{e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(test_http_v2())
    sys.exit(0 if success else 1)
