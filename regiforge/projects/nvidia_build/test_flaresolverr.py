"""NVIDIA HTTP 模式 - 使用 FlareSolverr 处理 Cloudflare

流程：
1. 调用 FlareSolverr 解决 build.nvidia.com 的 Cloudflare
2. 获取 cf_clearance Cookie 和 User-Agent
3. 使用 Cookie 访问 NVGS 完成注册
"""
import asyncio
import json
import sys
from pathlib import Path

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))

from captcha.cloudflare.flaresolverr.provider import FlareSolverrProvider


async def test_flaresolverr_nvidia():
    """测试使用 FlareSolverr 访问 build.nvidia.com"""
    print("=" * 60)
    print("NVIDIA - FlareSolverr 测试")
    print("=" * 60)
    
    # 创建 FlareSolverr Provider
    provider = FlareSolverrProvider()
    
    # 配置 FlareSolverr 服务
    # FlareSolverr 3.x 部署在 192.6.121.16:8191，直连访问目标（3.x 不再支持 proxy 参数）
    provider.configure({
        "api_url": "http://192.6.121.16:8191/v1",
        "max_timeout": 60000,
    })

    print("\n🌐 目标 URL: https://build.nvidia.com/?modal=signin")
    print("🔧 FlareSolverr: http://192.6.121.16:8191/v1")
    print("📡 出口：FlareSolverr 服务器直连（3.x 不支持 proxy）")
    print("=" * 60)
    
    try:
        # 调用 FlareSolverr
        print("\n🚀 开始解决 Cloudflare 挑战...")
        result = await provider.solve(
            page_url="https://build.nvidia.com/?modal=signin",
        )
        
        if not result:
            print("\n❌ FlareSolverr 返回 None")
            return False
        
        # 解析结果
        data = json.loads(result)
        
        print("\n✅ FlareSolverr 成功！")
        print(f"  - cf_clearance: {data.get('cf_clearance', '')[:30]}...")
        print(f"  - User-Agent: {data.get('ua', '')[:50]}...")
        print(f"  - Cookie 数量：{len(data.get('cookies', []))}")
        print(f"  - 状态码：{data.get('status', 200)}")
        print(f"  - 最终 URL: {data.get('url', '')[:60]}...")
        
        # 检查是否成功
        if data.get('cf_clearance'):
            print("\n✅ 获取到 cf_clearance Cookie！")
            print("💡 可以使用这个 Cookie 访问 build.nvidia.com 和 NVGS")
            
            # 保存结果
            output_file = root_dir / "data" / "flaresolverr_result.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"💾 结果已保存到：{output_file}")
            
            return True
        else:
            print("\n❌ 未获取到 cf_clearance Cookie")
            return False
            
    except Exception as e:
        print(f"\n❌ 异常：{e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(test_flaresolverr_nvidia())
    sys.exit(0 if success else 1)
