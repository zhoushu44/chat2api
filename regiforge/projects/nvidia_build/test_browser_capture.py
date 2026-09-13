"""NVIDIA 注册流程抓包辅助脚本 - 用于分析实际 URL 和字段"""
import asyncio
import json
from pathlib import Path
import sys

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))

from core.models import RunContext, AccountResult
from projects.nvidia_build.project import NvidiaBuildProject

async def test_with_logging():
    """用 browser 模式跑一次，记录所有网络请求"""
    print("=" * 60)
    print("NVIDIA 注册流程 - 网络请求分析")
    print("=" * 60)
    
    # 构造一个简化的 RunContext
    config_path = root_dir / "data" / "config.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    else:
        config = {}
    
    # 生成测试邮箱
    import random
    test_email = f"{''.join(str(random.randint(0, 9)) for _ in range(8))}@zhoushu.kdns.fr"
    test_password = "zs1236547."
    
    print(f"\n测试邮箱：{test_email}")
    print(f"测试密码：{test_password}")
    print("=" * 60)
    
    # 创建 mock context
    class MockProxy:
        async def acquire(self):
            return None
        async def release(self, info):
            pass
    
    class MockEmail:
        def generate_address(self):
            return test_email
        async def wait_code(self, email, timeout=120):
            print(f"\n[邮箱] 等待验证码：{email}")
            # 这里可以手动输入
            code = input(f"请输入邮箱验证码（{timeout}s 内）：")
            return code
    
    class MockCaptcha:
        async def solve(self, sitekey, page_url, timeout=180):
            print(f"\n[验证码] sitekey={sitekey[:30]}...")
            print(f"[验证码] page_url={page_url[:60]}...")
            # 这里可以对接真实的验证码服务
            # 为了测试，返回一个假 token
            return "test_token_" + "x" * 200
    
    class MockLog:
        def __call__(self, msg):
            print(f"[LOG] {msg}")
    
    ctx = RunContext(
        config=config,
        proxy=MockProxy(),
        email=MockEmail(),
        captcha=MockCaptcha(),
        log=MockLog(),
    )
    
    # 运行 project
    project = NvidiaBuildProject()
    
    print("\n开始运行 browser 模式注册...")
    print("注意：请在浏览器中观察网络请求！")
    print("=" * 60)
    
    try:
        result = await project.run_one(ctx)
        print("\n" + "=" * 60)
        print(f"注册结果：{result.status}")
        print(f"API Key: {result.apikey[:20] if result.apikey else 'None'}...")
        print("=" * 60)
    except Exception as e:
        print(f"\n❌ 异常：{e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_with_logging())
