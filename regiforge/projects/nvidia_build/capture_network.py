"""NVIDIA Browser 模式 - 网络请求监控

运行 browser 模式注册，记录所有网络请求用于分析
"""
import asyncio
import json
import sys
from pathlib import Path

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))

# 启用 Playwright 网络请求日志
import os
os.environ["DEBUG"] = "pw:protocol"

from core.models import RunContext
from projects.nvidia_build.project import NvidiaBuildProject


async def test_with_network_monitor():
    """运行 browser 模式，监控网络请求"""
    print("=" * 60)
    print("NVIDIA Browser 模式 - 网络请求监控")
    print("=" * 60)
    
    # 加载配置
    config_path = root_dir / "data" / "config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    
    # 设置 browser 模式
    if "projects" not in config:
        config["projects"] = {}
    if "nvidia_build" not in config["projects"]:
        config["projects"]["nvidia_build"] = {}
    
    config["projects"]["nvidia_build"]["register_mode"] = "browser"
    config["projects"]["nvidia_build"]["browser_backend"] = "playwright"
    config["projects"]["nvidia_build"]["browser_channel"] = "chrome"
    
    # 生成测试邮箱
    import random
    test_email = f"{''.join(str(random.randint(0, 9)) for _ in range(8))}@zhoushu.kdns.fr"
    test_password = "zs1236547."
    
    print(f"\n📧 测试邮箱：{test_email}")
    print(f"🔑 测试密码：{test_password}")
    print(f"🌐 注册模式：browser (playwright)")
    print("=" * 60)
    
    # 创建 mock context
    class MockProxy:
        async def acquire(self):
            proxy_cfg = config.get("proxy", {}).get("socks5", {})
            if proxy_cfg.get("server"):
                return type("ProxyInfo", (), {
                    "server": proxy_cfg["server"],
                    "username": proxy_cfg.get("username", ""),
                    "password": proxy_cfg.get("password", ""),
                    "meta": {}
                })()
            return None
        async def release(self, info):
            pass
    
    class MockEmail:
        def generate_address(self):
            return test_email
        async def wait_code(self, email, timeout=120):
            print(f"\n[邮箱] 等待验证码：{email}")
            # 等待用户手动输入
            try:
                print("💡 请在浏览器中查看邮箱验证码，然后输入：")
                code = input(f"验证码：")
                return code
            except Exception as e:
                print(f"读取验证码失败：{e}")
                return None
    
    class MockCaptcha:
        async def solve(self, sitekey, page_url, timeout=180, **kwargs):
            print(f"\n[验证码] 🧩 sitekey={sitekey}")
            print(f"[验证码] 🌐 page_url={page_url}")
            # 实际调用 CaptchaRun
            print("[验证码] 正在解题...")
            await asyncio.sleep(3)
            # 返回测试 token
            token = "test_token_" + "x" * 200
            print(f"[验证码] ✅ token={token[:30]}...")
            return token
    
    captured_requests = []
    
    class MockLog:
        def __call__(self, msg):
            print(f"[LOG] {msg}")
            # 捕获关键日志
            if "http" in msg.lower() or "url" in msg.lower() or "post" in msg.lower() or "get" in msg.lower():
                captured_requests.append(msg)
    
    ctx = RunContext(
        config=config,
        proxy=MockProxy(),
        email=MockEmail(),
        captcha=MockCaptcha(),
        log=MockLog(),
    )
    
    # 运行 project
    project = NvidiaBuildProject()
    
    print("\n🚀 开始运行 browser 模式注册...")
    print("💡 提示：浏览器会自动打开，请观察网络请求（F12 → Network）")
    print("=" * 60)
    
    try:
        result = await project.run_one(ctx)
        
        print("\n" + "=" * 60)
        print(f"✅ 注册完成：{result.status}")
        if result.apikey:
            print(f"🎉 API Key: {result.apikey[:20]}...")
        else:
            print(f"❌ 错误：{result.error}")
            print(f"📍 失败步骤：{result.failed_step}")
            print(f"🏷️  失败分类：{result.failure_class}")
        
        # 保存捕获的请求
        if captured_requests:
            print(f"\n📦 捕获到 {len(captured_requests)} 个网络请求")
            output_file = root_dir / "data" / "debug" / "nvidia_build" / "network_requests.json"
            output_file.parent.mkdir(parents=True, exist_ok=True)
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(captured_requests, f, indent=2, ensure_ascii=False)
            print(f"💾 已保存到：{output_file}")
        
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ 异常：{e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_with_network_monitor())
