"""CapSolver Turnstile Provider — AntiTurnstileTaskProxyLess.

通过 CapSolver API 自动解决 Cloudflare Turnstile 挑战。
不需要代理信息（ProxyLess），Turnstile token 不绑定客户端 IP，
可直接注入到任何浏览器会话。

API 文档: https://docs.capsolver.com/en/guide/captcha/cloudflare_turnstile
"""
from __future__ import annotations

import asyncio
from typing import Any

import requests
import urllib3

from core.base import CaptchaProvider

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class CapSolverTurnstileProvider(CaptchaProvider):
    """通过 CapSolver API 自动解决 Turnstile 挑战（ProxyLess）。

    注入 token 到页面的 cf-turnstile-response input，触发回调。
    不需要代理信息（Turnstile token 与客户端 IP 无关）。
    """

    type = "turnstile"
    id = "capsolver"
    name = "CapSolver (Turnstile ProxyLess)"

    # 已知站点 sitekey 兜底（避免在页面上检测失败时卡住）
    _KNOWN_SITEKEYS: dict[str, str] = {
        "openai.com": "0x4AAAAAAAx1CyDNL8zOEPe7",
        "auth0.com": "0x4AAAAAAAx1CyDNL8zOEPe7",
    }

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}

    async def solve(self, *, sitekey: str, page_url: str, **kwargs: Any) -> str | None:
        api_key = (self._config.get("api_key") or "").strip()
        if not api_key:
            raise RuntimeError("CapSolver api_key 未配置，请在页面配置中填写")

        api_url = (self._config.get("api_url") or "https://api.capsolver.com").rstrip("/")
        poll_interval = float(self._config.get("poll_interval") or 2)
        max_poll = int(self._config.get("max_poll") or 60)
        page = kwargs.get("page")

        # ── 提取 sitekey ──────────────────────────────────────────
        actual_sitekey = sitekey or ""
        if not actual_sitekey and page is not None:
            actual_sitekey = await self._extract_sitekey(page)

        # 兜底：已知站点 sitekey
        if not actual_sitekey:
            page_url_lower = (page_url or "").lower()
            for domain, sk in self._KNOWN_SITEKEYS.items():
                if domain in page_url_lower:
                    actual_sitekey = sk
                    print(f"[turnstile.capsolver] 使用已知 sitekey 兜底: {actual_sitekey} (domain={domain})", flush=True)
                    break

        if not actual_sitekey:
            raise RuntimeError("无法获取 Turnstile sitekey，请确保页面上有 turnstile 挂件")

        # 清理 page_url（去掉查询参数和 hash，CapSolver 只需主页面地址）
        clean_url = page_url.split("?", 1)[0].split("#", 1)[0] if page_url else ""

        # ── 创建任务 ──────────────────────────────────────────────
        payload = {
            "clientKey": api_key,
            "task": {
                "type": "AntiTurnstileTaskProxyLess",
                "websiteURL": clean_url,
                "websiteKey": actual_sitekey,
            },
        }

        def create_task() -> str:
            resp = requests.post(
                f"{api_url}/createTask",
                json=payload,
                timeout=30,
                verify=False,
            )
            data = resp.json()
            error_id = data.get("errorId", 1)
            if error_id != 0:
                desc = data.get("errorDescription", resp.text[:200])
                raise RuntimeError(f"CapSolver 创建任务失败: {desc}")
            task_id = data.get("taskId")
            if not task_id:
                raise RuntimeError(f"CapSolver 响应无 taskId: {data}")
            print(f"[turnstile.capsolver] 任务已创建: taskId={task_id} sitekey={actual_sitekey}", flush=True)
            return task_id

        task_id = await asyncio.to_thread(create_task)

        # ── 轮询结果 ──────────────────────────────────────────────
        result_payload = {"clientKey": api_key, "taskId": task_id}

        def poll_once() -> str | None:
            resp = requests.post(
                f"{api_url}/getTaskResult",
                json=result_payload,
                timeout=15,
                verify=False,
            )
            data = resp.json()
            error_id = data.get("errorId", 1)
            if error_id != 0:
                desc = data.get("errorDescription", "unknown")
                raise RuntimeError(f"CapSolver 任务失败: {desc}")
            status = data.get("status", "")
            if status == "processing":
                return None
            if status != "ready":
                return None
            solution = data.get("solution", {})
            if not isinstance(solution, dict):
                return None
            token = solution.get("token") or ""
            if not token:
                return None
            return token

        for i in range(max_poll):
            await asyncio.sleep(poll_interval)
            token = await asyncio.to_thread(poll_once)
            if token:
                print(f"[turnstile.capsolver] Turnstile token 已获取（长度 {len(token)}，轮询 {i+1} 次）", flush=True)
                return token

        raise RuntimeError(f"CapSolver Turnstile 超时（{max_poll * poll_interval}s）")

    # ── 内部方法 ──────────────────────────────────────────────────

    async def _extract_sitekey(self, page) -> str:
        """从页面 DOM 提取 Turnstile sitekey，多轮重试。"""
        for attempt in range(3):
            try:
                await page.wait_for_selector(
                    'iframe[src*="challenges.cloudflare.com"], iframe[src*="turnstile"], '
                    '.cf-turnstile, [data-sitekey], #challenge-stage, #cf-challenge-running',
                    timeout=10_000,
                )
            except Exception:
                pass

            try:
                sitekey = await page.evaluate(
                    """() => {
                        // 1. data-sitekey 属性
                        const el = document.querySelector('[data-sitekey]');
                        if (el) {
                            const v = el.getAttribute('data-sitekey');
                            if (v) return v;
                        }
                        // 2. iframe src 中的 sitekey 参数
                        const iframes = document.querySelectorAll('iframe');
                        for (const iframe of iframes) {
                            const src = iframe.getAttribute('src') || '';
                            const m = src.match(/[?&]sitekey=([^&]+)/);
                            if (m) return decodeURIComponent(m[1]);
                        }
                        // 3. Cloudflare iframe 的 k= 参数
                        const cfIframe = document.querySelector('iframe[src*="challenges.cloudflare.com"], iframe[src*="turnstile"]');
                        if (cfIframe) {
                            const src = cfIframe.getAttribute('src') || '';
                            const m2 = src.match(/[?&]k=([0-9a-zA-Z_-]{20,})/);
                            if (m2) return m2[1];
                        }
                        // 4. 内联 script 中的 sitekey
                        const scripts = Array.from(document.querySelectorAll('script:not([src])'));
                        for (const s of scripts) {
                            const text = s.textContent || '';
                            const m = text.match(/sitekey\\s*[:=]\\s*["']([0-9a-zA-Z_-]{20,})["']/);
                            if (m) return m[1];
                        }
                        return '';
                    }"""
                )
                if sitekey:
                    return sitekey
            except Exception as exc:
                print(f"[turnstile.capsolver] sitekey 检测失败 (attempt {attempt}): {exc}", flush=True)

            if attempt < 2:
                await asyncio.sleep(5)

        return ""


PROVIDER = CapSolverTurnstileProvider()


