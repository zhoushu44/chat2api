"""NVIDIA HTTP 模式 - L3 验收测试

L3 标准：同配置提高并发（先 2），批量 total，成功率较 L2 跌幅 ≤15%
  - L2 成功率 80% → L3 须 ≥ 65%

并发模型（对齐 core/task_runner.py 生产实现）：
  - asyncio.Semaphore(concurrency) 限制并发
  - stagger 错开启动：delay = (idx - start) * stagger
  - 共享 Provider 实例（captcha/email/proxy 各一份，并发复用）
  - asyncio.create_task + asyncio.gather

使用真实 Provider（与 L2 相同）：
  - 验证码：hcaptcha.captcharun
  - 邮箱：tempmail
  - 代理：socks5（含认证转发器，并发共享同一上游）
"""
import asyncio
import json
import sys
import time
from pathlib import Path

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))

from core.base import RunContext
from core.models import AccountResult
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
            # 重置代理池状态（对齐 task_runner）
            server_config = str(cfg.get("server") or "").strip()
            proxy_lines = [line.strip() for line in server_config.split("\n") if line.strip()]
            if hasattr(PROVIDER, "_proxy_pool"):
                PROVIDER._proxy_pool = proxy_lines
                PROVIDER._proxy_index = 0
            if hasattr(PROVIDER, "_failed_proxies"):
                PROVIDER._failed_proxies.clear()
            return PROVIDER
        raise ValueError(f"未支持的 proxy provider: {provider_id}")
    raise ValueError(f"未知 kind: {kind}")


async def test_l3_batch():
    """L3 验收：concurrency=2, total=6, stagger=5, 成功率≥65%"""
    TOTAL = 6
    CONCURRENCY = 2
    STAGGER = 5  # 错开启动秒数（对齐 project_state.stagger）
    L2_SUCCESS_RATE = 80.0  # L2 基准
    MAX_DROP = 15.0  # 允许跌幅
    THRESHOLD = L2_SUCCESS_RATE - MAX_DROP  # = 65%

    print("=" * 60)
    print(f"NVIDIA HTTP 模式 - L3 验收测试")
    print(f"  total={TOTAL}, concurrency={CONCURRENCY}, stagger={STAGGER}s")
    print(f"  成功率门槛: ≥{THRESHOLD:.0f}% (L2={L2_SUCCESS_RATE:.0f}%, 跌幅≤{MAX_DROP:.0f}%)")
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

    # Provider（共享实例，对齐 task_runner 生产模式）
    project_state = (config.get("ui") or {}).get("project_state") or {}
    nv_state = project_state.get("nvidia_build") or {}
    captcha_id = nv_state.get("captcha_id") or "hcaptcha.captcharun"
    email_id = "tempmail"
    proxy_id = nv_state.get("proxy_id") or "socks5"

    print(f"验证码 Provider: {captcha_id}")
    print(f"邮箱 Provider:   {email_id}")
    print(f"代理 Provider:   {proxy_id}")
    print("=" * 60)

    # 共享 Provider 实例（并发复用，对齐生产 task_runner）
    captcha_provider = _load_provider(config, "captcha", captcha_id)
    email_provider = _load_provider(config, "email", email_id)
    proxy_provider = _load_provider(config, "proxy", proxy_id)

    project = NvidiaBuildProject()
    sem = asyncio.Semaphore(CONCURRENCY)
    results: list[AccountResult | None] = [None] * TOTAL
    emails: list[str] = [""] * TOTAL
    start_idx = 1

    async def run_one(idx: int):
        """单个注册任务（对齐 task_runner.run_one 结构）。"""
        # stagger 错开启动
        if STAGGER > 0 and idx > start_idx:
            delay = (idx - start_idx) * STAGGER
            print(f"[{idx}/{TOTAL}] 错开启动，等待 {delay}s ...")
            await asyncio.sleep(delay)

        async with sem:
            print(f"\n{'='*60}")
            print(f"[{idx}/{TOTAL}] 开始注册（并发槽位已获取）...")
            print(f"{'='*60}")

            # 生成邮箱（sync 调用，短暂阻塞可接受）
            try:
                test_email = email_provider.generate_address()
                emails[idx - start_idx] = test_email
            except Exception as e:
                print(f"[{idx}/{TOTAL}] ❌ 邮箱生成失败: {e}")
                results[idx - start_idx] = AccountResult(
                    status="fail", email="", error=f"邮箱生成失败: {e}",
                    failure_class="exception", failed_step="email_generate",
                )
                return

            print(f"[{idx}/{TOTAL}] 邮箱: {test_email}")

            def log_fn(msg: str, _idx=idx):
                print(f"[LOG] [{_idx}/{TOTAL}] {msg}")

            ctx = RunContext(
                task_id="test_l3_http",
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
                results[idx - start_idx] = result
                if result.apikey:
                    print(f"[{idx}/{TOTAL}] ✅ 成功: {result.apikey[:30]}...")
                else:
                    print(f"[{idx}/{TOTAL}] ❌ 失败: step={result.failed_step} class={result.failure_class} err={result.error}")
            except Exception as e:
                print(f"[{idx}/{TOTAL}] ❌ 异常: {e}")
                results[idx - start_idx] = AccountResult(
                    status=f"exception: {e}", email=test_email,
                    error=str(e), failure_class="exception",
                )

    # 启动所有任务（对齐 task_runner: create_task + gather）
    t0 = time.perf_counter()
    tasks = [asyncio.create_task(run_one(start_idx + i)) for i in range(TOTAL)]
    await asyncio.gather(*tasks)
    elapsed = time.perf_counter() - t0

    # 汇总
    print("\n" + "=" * 60)
    print("L3 验收汇总")
    print("=" * 60)
    ok_count = sum(1 for r in results if r and r.apikey)
    fail_count = len(results) - ok_count
    success_rate = (ok_count / len(results) * 100) if results else 0

    for i, r in enumerate(results):
        idx = start_idx + i
        email = emails[i] or "(无邮箱)"
        if r and r.apikey:
            print(f"  ✅ [{idx}/{TOTAL}] {email[:30]:30s} key={r.apikey[:24]}...")
        elif r:
            print(f"  ❌ [{idx}/{TOTAL}] {email[:30]:30s} step={r.failed_step} class={r.failure_class} err={(r.error or '')[:60]}")
        else:
            print(f"  ❌ [{idx}/{TOTAL}] {email[:30]:30s} (无结果)")

    # 失败分类统计
    fail_classes: dict[str, int] = {}
    for r in results:
        if r and not r.apikey:
            fc = r.failure_class or "unknown"
            fail_classes[fc] = fail_classes.get(fc, 0) + 1

    print(f"\n成功: {ok_count}/{len(results)}, 失败: {fail_count}")
    print(f"成功率: {success_rate:.1f}%")
    print(f"总耗时: {elapsed:.0f}s (avg {elapsed/len(results):.0f}s/账号)")
    if fail_classes:
        print(f"失败分类: {fail_classes}")

    # L3 判定
    drop = L2_SUCCESS_RATE - success_rate
    print(f"\nL2 基准: {L2_SUCCESS_RATE:.0f}%, 当前: {success_rate:.1f}%, 跌幅: {drop:.1f}%")

    if success_rate >= THRESHOLD:
        print(f"\n✅ L3 验收通过！（成功率 {success_rate:.1f}% ≥ {THRESHOLD:.0f}%, 跌幅 {drop:.1f}% ≤ {MAX_DROP:.0f}%）")
        return True
    else:
        print(f"\n❌ L3 验收失败（成功率 {success_rate:.1f}% < {THRESHOLD:.0f}%, 跌幅 {drop:.1f}% > {MAX_DROP:.0f}%）")
        print("\n失败详情（用于卡级修复）：")
        for i, r in enumerate(results):
            if r and not r.apikey:
                idx = start_idx + i
                print(f"  [{idx}] step={r.failed_step} class={r.failure_class} err={r.error}")
                if r.evidence_dir:
                    print(f"       evidence={r.evidence_dir}")
        return False


if __name__ == "__main__":
    success = asyncio.run(test_l3_batch())
    sys.exit(0 if success else 1)
