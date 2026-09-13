"""NVIDIA 混合模式注册 - Browser + HTTP

流程：
1. Browser 模式：访问 build.nvidia.com → 获取 key 和 Cookie
2. HTTP 模式：使用 key 和 Cookie 完成后续注册流程
"""
import asyncio
import json
import sys
from pathlib import Path

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))

from core.base import RunContext
from core.models import AccountResult
from projects.nvidia_build.project import NvidiaBuildProject
from playwright.async_api import async_playwright


async def extract_key_and_cookies(page, context):
    """从 browser 模式提取 key 和 Cookie"""
    context.log("提取 key 和 Cookie...")
    
    # 1. 访问 build.nvidia.com
    await page.goto("https://build.nvidia.com/?modal=signin", wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)  # 等待 JS 执行
    
    # 2. 从页面提取 key（从 JS 变量或 meta 标签）
    key = await page.evaluate("""() => {
        // 尝试从 window 对象获取
        if (window.__INITIAL_STATE__ && window.__INITIAL_STATE__.key) {
            return window.__INITIAL_STATE__.key;
        }
        // 尝试从 meta 标签获取
        const meta = document.querySelector('meta[name="key"]');
        if (meta) {
            return meta.content;
        }
        // 尝试从 data 属性获取
        const app = document.querySelector('[data-key]');
        if (app) {
            return app.dataset.key;
        }
        return null;
    }""")
    
    context.log(f"提取到 key: {key[:20] if key else 'None'}...")
    
    # 3. 获取 Cookie
    cookies = await context.cookies()
    cookie_dict = {c["name"]: c["value"] for c in cookies}
    
    context.log(f"提取到 {len(cookies)} 个 Cookie")
    
    return key, cookie_dict


async def test_hybrid_mode():
    """测试混合模式：Browser + HTTP"""
    print("=" * 60)
    print("NVIDIA 混合模式测试 - Browser + HTTP")
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
            try:
                code = input(f"请输入邮箱验证码：")
                return code
            except:
                return None
    
    class MockCaptcha:
        async def solve(self, sitekey, page_url, timeout=180, **kwargs):
            print(f"\n[验证码] 🧩 sitekey={sitekey}")
            print(f"[验证码] 🌐 page_url={page_url}")
            print("[验证码] 正在解题...")
            await asyncio.sleep(3)
            token = "test_token_" + "x" * 200
            print(f"[验证码] ✅ token={token[:30]}...")
            return token
    
    def log_fn(msg):
        print(f"[LOG] {msg}")
    
    ctx = RunContext(
        task_id="test_hybrid",
        index=1,
        total=1,
        config=config,
        proxy=MockProxy(),
        email=MockEmail(),
        captcha=MockCaptcha(),
        headless=False,
        logger=log_fn,
    )
    
    print("\n🚀 开始混合模式测试...")
    print("步骤 1: Browser 模式获取 key 和 Cookie")
    print("步骤 2: HTTP 模式完成注册")
    print("=" * 60)
    
    try:
        # 步骤 1: 启动浏览器
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context()
            page = await context.new_page()
            
            # 提取 key 和 Cookie
            key, cookie_dict = await extract_key_and_cookies(page, ctx)
            
            if not key:
                print("\n❌ 无法提取 key，需要手动分析页面结构")
                return False
            
            await browser.close()
            
            # 步骤 2: 使用 HTTP 模式（带 key 和 Cookie）
            print("\n✅ 步骤 1 完成，开始步骤 2（HTTP 模式）")
            print(f"Key: {key[:20]}...")
            print(f"Cookie 数量：{len(cookie_dict)}")
            
            # TODO: 调用 HTTP 引擎，传入 key 和 Cookie
            # 这需要修改 _http_engine.py 支持传入 key 和 Cookie
            
            print("\n⚠️  需要实现：HTTP 引擎接收 key 和 Cookie 的参数")
            return True
            
    except Exception as e:
        print(f"\n❌ 异常：{e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(test_hybrid_mode())
    sys.exit(0 if success else 1)
