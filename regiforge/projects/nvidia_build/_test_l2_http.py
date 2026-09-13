"""NVIDIA HTTP 模式 - L2 验收测试

L2 标准：同配置 concurrency=1, total≥5, 成功率≥80%

使用真实 Provider：
  - 验证码：hcaptcha.captcharun
  - 邮箱：tempmail
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
        raise ValueError(f"未支持的 proxy provider: {provider_id}")
    raise ValueError(f"未知 kind: {kind}")


async def test_l2_batch():
    """L2 验收：total=5, concurrency=1, 成功率≥80%"""
    TOTAL = 5
    print("=" * 60)
    print(f"NVIDIA HTTP 模式 - L2 验收测试（total={TOTAL}, concurrency=1）")
    print("=" * 60)

    # 加载配置
    config_path = root_dir / "data" / "config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    # 设置 HTTP 模式
    config.setdefault("projects", {}).setdefault("nvidia_build", {})
    config["projects"]["nvidia_build"]["register_mode"] = "http"
    config["projects"]["nvidia_build"]["browser_backend"] = "playwright"

    # tempmail 代理
    config.setdefault("email", {}).setdefault("tempmail", {})
    if not config["email"]["tempmail"].get("proxy"):
        config["email"]["tempmail"]["proxy"] = "socks5://sockstest:socks-pass%401@192.6.121.16:7890"

    # Provider
    project_state = (config.get("ui") or {}).get("project_state") or {}
    nv_state = project_state.get("nvidia_build") or {}
    captcha_id = nv_state.get("captcha_id") or "hcaptcha.captcharun"
    email_id = "tempmail"
    proxy_id = nv_state.get("proxy_id") or "socks5"

    print(f"验证码 Provider: {captcha_id}")
    print(f"邮箱 Provider:   {email_id}")
    print(f"代理 Provider:   {proxy_id}")
    print(f"总数: {TOTAL}, 并发: 1")
    print("=" * 60)

    captcha_provider = _load_provider(config, "captcha", captcha_id)
    email_provider = _load_provider(config, "email", email_id)
    proxy_provider = _load_provider(config, "proxy", proxy_id)

    test_password = config["projects"]["nvidia_build"].get("password") or "zs1236547."
    project = NvidiaBuildProject()

    results = []  # list of (index, email, status, apikey, error)

    for idx in range(1, TOTAL + 1):
        if idx > 1:
            print(f"\n[等待] 账号间间隔 30s（让代理恢复）...")
            await asyncio.sleep(30)

        print(f"\n{'='*60}")
        print(f"[{idx}/{TOTAL}] 开始注册 ...")
        print(f"{'='*60}")

        # 每次重新加载 Provider（确保 proxy forwarder 新建）
        proxy_provider = _load_provider(config, "proxy", proxy_id)
        email_provider = _load_provider(config, "email", email_id)

        try:
            test_email = email_provider.generate_address()
        except Exception as e:
            print(f"[{idx}/{TOTAL}] ❌ 邮箱生成失败: {e}")
            results.append((idx, "", "fail", None, f"邮箱生成失败: {e}"))
            continue

        print(f"[{idx}/{TOTAL}] 邮箱: {test_email}")

        def log_fn(msg: str, _idx=idx):
            print(f"[LOG] [{_idx}/{TOTAL}] {msg}")

        ctx = RunContext(
            task_id="test_l2_http",
            index=idx,
            total=TOTAL,
            config=config,
            proxy=proxy_provider,
            email=email_provider,
            captcha=captcha_provider,
            headless=False,
            logger=log_fn,
        )

        try:
            result = await project.run_one(ctx)
            if result.apikey:
                print(f"[{idx}/{TOTAL}] ✅ 成功: {result.apikey[:30]}...")
                results.append((idx, test_email, "ok", result.apikey, None))
            else:
                print(f"[{idx}/{TOTAL}] ❌ 失败: {result.error}")
                results.append((idx, test_email, "fail", None, result.error))
        except Exception as e:
            print(f"[{idx}/{TOTAL}] ❌ 异常: {e}")
            import traceback
            traceback.print_exc()
            results.append((idx, test_email, "fail", None, str(e)))

    # 汇总
    print("\n" + "=" * 60)
    print("L2 验收汇总")
    print("=" * 60)
    ok_count = sum(1 for r in results if r[2] == "ok")
    fail_count = len(results) - ok_count
    success_rate = (ok_count / len(results) * 100) if results else 0

    for idx, email, status, apikey, error in results:
        icon = "✅" if status == "ok" else "❌"
        key_str = apikey[:20] + "..." if apikey else "N/A"
        print(f"  {icon} [{idx}/{TOTAL}] {email[:30]:30s} key={key_str}")

    print(f"\n成功: {ok_count}/{len(results)}, 失败: {fail_count}")
    print(f"成功率: {success_rate:.1f}%")

    if success_rate >= 80:
        print(f"\n✅ L2 验收通过！（成功率 {success_rate:.1f}% ≥ 80%）")
        return True
    else:
        print(f"\n❌ L2 验收失败（成功率 {success_rate:.1f}% < 80%）")
        # 输出失败原因
        for idx, email, status, apikey, error in results:
            if status != "ok":
                print(f"  失败 [{idx}] {email}: {error}")
        return False


if __name__ == "__main__":
    success = asyncio.run(test_l2_batch())
    sys.exit(0 if success else 1)
