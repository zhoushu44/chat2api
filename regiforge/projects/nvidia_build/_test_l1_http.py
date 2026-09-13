"""NVIDIA HTTP 模式 - L1 验收测试

测试单个账号 HTTP 模式注册是否成功（混合：浏览器过 CF + curl_cffi 注册 + 浏览器接管 OTP/API Key）

使用真实 Provider：
  - 验证码：hcaptcha.captcharun
  - 邮箱：cloudflare_worker
  - 代理：socks5（含认证转发器）
"""
import asyncio
import json
import sys
from pathlib import Path

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))

from core.base import RunContext
from projects.nvidia_build.project import NvidiaBuildProject


def _load_provider(config: dict, kind: str, provider_id: str):
    """根据 kind/provider_id 加载真实 Provider 并 configure。"""
    if kind == "captcha":
        # provider_id 形如 "hcaptcha.captcharun"
        parts = provider_id.split(".", 1)
        if len(parts) != 2:
            raise ValueError(f"无效 captcha_id: {provider_id}")
        ctype, vendor = parts
        vendor_cfg = (config.get("captcha") or {}).get(ctype) or {}
        cfg = vendor_cfg.get(vendor) or {}
        if ctype == "hcaptcha" and vendor == "captcharun":
            from captcha.hcaptcha.captcharun.provider import PROVIDER
            PROVIDER.configure(cfg)
            return PROVIDER
        raise ValueError(f"未支持的 captcha provider: {provider_id}")
    if kind == "email":
        cfg = (config.get("email") or {}).get(provider_id) or {}
        if provider_id == "cloudflare_worker":
            from mailsys.cloudflare_worker.provider import PROVIDER
            PROVIDER.configure(cfg)
            return PROVIDER
        if provider_id == "tempmail":
            from mailsys.tempmail.provider import PROVIDER
            PROVIDER.configure(cfg)
            return PROVIDER
        raise ValueError(f"未支持的 email provider: {provider_id}")
    if kind == "proxy":
        cfg = (config.get("proxy") or {}).get(provider_id) or {}
        if provider_id == "socks5":
            from proxy.socks5.provider import PROVIDER
            PROVIDER.configure(cfg)
            return PROVIDER
        if provider_id == "none":
            from proxy.none.provider import PROVIDER
            PROVIDER.configure(cfg)
            return PROVIDER
        raise ValueError(f"未支持的 proxy provider: {provider_id}")
    raise ValueError(f"未知 kind: {kind}")


async def test_l1_single():
    """L1 验收：total=1, concurrency=1, register_mode=http"""
    print("=" * 60)
    print("NVIDIA HTTP 模式 - L1 验收测试（混合引擎）")
    print("=" * 60)

    # 加载配置
    config_path = root_dir / "data" / "config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    # 设置 HTTP 模式
    config.setdefault("projects", {}).setdefault("nvidia_build", {})
    config["projects"]["nvidia_build"]["register_mode"] = "http"
    # 使用 playwright 底座（patchright 有 asyncio 兼容性问题）
    config["projects"]["nvidia_build"]["browser_backend"] = "playwright"

    # 使用 tempmail 邮箱（支持 wait_link 验证链接提取，cloudflare_worker CloudMail API 当前不可用）
    # 给 tempmail 配置代理（API 在国内需走代理）
    config.setdefault("email", {}).setdefault("tempmail", {})
    if not config["email"]["tempmail"].get("proxy"):
        config["email"]["tempmail"]["proxy"] = "socks5://sockstest:socks-pass%401@192.6.121.16:7890"

    # 加载真实 Provider（从 ui.project_state 读取上次选择）
    project_state = (config.get("ui") or {}).get("project_state") or {}
    nv_state = project_state.get("nvidia_build") or {}
    captcha_id = nv_state.get("captcha_id") or "hcaptcha.captcharun"
    email_id = "tempmail"  # 强制使用 tempmail（支持验证链接提取）
    proxy_id = nv_state.get("proxy_id") or "socks5"

    print(f"验证码 Provider: {captcha_id}")
    print(f"邮箱 Provider:   {email_id}")
    print(f"代理 Provider:   {proxy_id}")

    captcha_provider = _load_provider(config, "captcha", captcha_id)
    email_provider = _load_provider(config, "email", email_id)
    proxy_provider = _load_provider(config, "proxy", proxy_id)

    # 生成测试邮箱
    test_email = email_provider.generate_address()
    test_password = config["projects"]["nvidia_build"].get("password") or "zs1236547."

    print(f"\n测试邮箱：{test_email}")
    print(f"测试密码：{test_password}")
    print(f"注册模式：http (混合引擎)")
    print("=" * 60)

    log_messages: list[str] = []

    def log_fn(msg: str):
        print(f"[LOG] {msg}")
        log_messages.append(msg)

    ctx = RunContext(
        task_id="test_l1_http",
        index=1,
        total=1,
        config=config,
        proxy=proxy_provider,
        email=email_provider,
        captcha=captcha_provider,
        headless=False,
        logger=log_fn,
    )

    # 运行 project
    project = NvidiaBuildProject()

    print("\n开始运行 HTTP 模式注册...")
    print("=" * 60)

    try:
        result = await project.run_one(ctx)

        print("\n" + "=" * 60)
        print(f"注册结果：{result.status}")
        if result.apikey:
            print(f"API Key: {result.apikey[:20]}...")
            print(f"邮箱: {result.email}")
            print("\n✅ L1 验收通过！")
            return True
        else:
            print(f"错误：{result.error}")
            print(f"失败步骤：{result.failed_step}")
            print(f"失败分类：{result.failure_class}")
            if result.evidence_dir:
                print(f"证据目录：{result.evidence_dir}")
            print("\n❌ L1 验收失败")
            return False
    except Exception as e:
        print(f"\n❌ 异常：{e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(test_l1_single())
    sys.exit(0 if success else 1)
