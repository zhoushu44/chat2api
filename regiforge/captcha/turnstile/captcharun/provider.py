from __future__ import annotations

import asyncio
from typing import Any

import requests
import urllib3

from core.base import CaptchaProvider

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class CaptchaRunTurnstileProvider(CaptchaProvider):
    """通过 CaptchaRun API 自动解决 Turnstile 挑战。

    注入 token 到页面的 cf-turnstile-response input，触发回调。
    不需要代理信息（Turnstile 与 CloudFlare5s 不同，不依赖客户端 IP）。
    """

    type = "turnstile"
    id = "captcharun"
    name = "CaptchaRun (Turnstile)"

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}

    async def solve(self, *, sitekey: str, page_url: str, **kwargs: Any) -> str | None:
        api_key = (self._config.get("api_key") or "").strip()
        if not api_key:
            raise RuntimeError("CaptchaRun api_key 未配置，请在页面配置中填写")

        api_url = (self._config.get("api_url") or "https://api.captcha-run.com/v2/tasks").rstrip("/")
        poll_interval = float(self._config.get("poll_interval") or 3)
        max_poll = int(self._config.get("max_poll") or 60)
        page = kwargs.get("page")
        proxy = kwargs.get("proxy") or self._config.get("proxy")
        proxies = {"http": proxy, "https": proxy} if proxy else None

        # 从页面提取 sitekey（如果未传入）
        actual_sitekey = sitekey or ""
        if not actual_sitekey and page is not None:
            # 分多轮尝试提取 sitekey，给 Turnstile widget 足够渲染时间
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
                    debug_info = await page.evaluate(
                        """() => {
                            const iframes = Array.from(document.querySelectorAll('iframe')).map(f => f.getAttribute('src') || '').slice(0, 8);
                            const dataKeys = Array.from(document.querySelectorAll('[data-sitekey]')).map(el => el.getAttribute('data-sitekey'));
                            const turnstileScripts = Array.from(document.querySelectorAll('script[src*="turnstile"]')).map(s => s.getAttribute('src'));
                            const hasCfTurnstile = !!document.querySelector('.cf-turnstile');
                            const hasChallengeStage = !!document.querySelector('#challenge-stage, #cf-challenge-running');
                            const bodyText = (document.body && document.body.innerText || '').slice(0, 200);
                            return JSON.stringify({iframes, dataKeys, turnstileScripts, hasCfTurnstile, hasChallengeStage, bodyText});
                        }"""
                    )
                    print(f"[turnstile.captcharun] page debug (attempt {0}): {debug_info}", flush=True)
                except Exception as exc:
                    print(f"[turnstile.captcharun] debug evaluate failed: {exc}", flush=True)

                try:
                    actual_sitekey = await page.evaluate(
                        """() => {
                            // 1. data-sitekey 属性
                            const el = document.querySelector('[data-sitekey]');
                            if (el) {
                                const v = el.getAttribute('data-sitekey');
                                if (v) return v;
                            }
                            // 2. 所有 iframe src 中的 sitekey 参数（含 Cloudflare challenge iframe）
                            const iframes = document.querySelectorAll('iframe');
                            for (const iframe of iframes) {
                                const src = iframe.getAttribute('src') || '';
                                const m = src.match(/[?&]sitekey=([^&]+)/);
                                if (m) return decodeURIComponent(m[1]);
                            }
                            // 3. Turnstile iframe src（更宽泛匹配）
                            const cfIframe = document.querySelector('iframe[src*="challenges.cloudflare.com"], iframe[src*="turnstile"]');
                            if (cfIframe) {
                                const src = cfIframe.getAttribute('src') || '';
                                const m = src.match(/[?&]sitekey=([^&]+)/);
                                if (m) return decodeURIComponent(m[1]);
                                // Cloudflare challenge iframe 的 k= 参数也可能是 sitekey
                                const m2 = src.match(/[?&]k=([0-9a-zA-Z_-]{20,})/);
                                if (m2) return m2[1];
                            }
                            // 4. window.turnstile 全局对象（OpenAI/Auth0 常用渲染方式）
                            if (typeof window.turnstile === 'object' && window.turnstile) {
                                const widgets = document.querySelectorAll('.cf-turnstile, [data-sitekey]');
                                for (const w of widgets) {
                                    const v = w.getAttribute('data-sitekey');
                                    if (v) return v;
                                }
                                // turnstile.getResponse() 有时能拿到已渲染 widget 的 sitekey
                                try {
                                    const container = document.querySelector('.cf-turnstile');
                                    if (container && container.id) {
                                        const widgetId = container.id;
                                    }
                                } catch {}
                            }
                            // 5. script 标签内联 render 调用
                            const scripts = Array.from(document.querySelectorAll('script:not([src])'));
                            for (const s of scripts) {
                                const text = s.textContent || '';
                                const m = text.match(/sitekey\s*[:=]\\s*["']([0-9a-zA-Z_-]{20,})["']/);
                                if (m) return m[1];
                            }
                            // 6. script[data-sitekey]
                            const s2 = document.querySelector('script[src*="turnstile"][data-sitekey]');
                            if (s2) return s2.getAttribute('data-sitekey') || '';
                            // 7. Cloudflare challenge 容器中的 sitekey
                            const challengeEl = document.querySelector('#challenge-stage, #cf-challenge-running, .challenge-platform');
                            if (challengeEl) {
                                const v = challengeEl.getAttribute('data-sitekey') || challengeEl.getAttribute('data-ray') || '';
                                // data-ray 不是 sitekey，跳过
                            }
                            return '';
                        }"""
                    )
                except Exception as exc:
                    print(f"[turnstile.captcharun] sitekey evaluate failed: {exc}", flush=True)

                if actual_sitekey:
                    break
                # 没找到 sitekey，等 5 秒再试
                if attempt < 2:
                    await asyncio.sleep(5)
        if not actual_sitekey:
            # 兜底：已知 OpenAI / auth0 的 Turnstile sitekey
            page_url_lower = (page_url or "").lower()
            if "openai.com" in page_url_lower or "auth0.com" in page_url_lower:
                actual_sitekey = "0x4AAAAAAAx1CyDNL8zOEPe7"
                print(f"[turnstile.captcharun] 使用 OpenAI 已知 sitekey 兜底: {actual_sitekey}", flush=True)
            else:
                raise RuntimeError("无法获取 Turnstile sitekey，请确保页面上有 turnstile 挂件")

        parsed = page_url.split("?", 1)[0] if page_url else ""
        payload = {
            "captchaType": "TurnstileTurnstile",
            "siteKey": actual_sitekey,
            "siteReferer": parsed,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        def create_task() -> str:
            resp = requests.post(api_url, headers=headers, json=payload, timeout=30, verify=False, proxies=proxies)
            if resp.status_code not in (200, 201):
                raise RuntimeError(f"CaptchaRun Turnstile 创建任务失败: HTTP {resp.status_code} {resp.text[:200]}")
            data = resp.json()
            task_id = data.get("taskId")
            if not task_id:
                raise RuntimeError(f"CaptchaRun Turnstile 响应无 taskId: {data}")
            return task_id

        task_id = await asyncio.to_thread(create_task)

        def poll_once() -> str | None:
            resp = requests.get(f"{api_url}/{task_id}", headers=headers, timeout=15, verify=False, proxies=proxies)
            if resp.status_code != 200:
                return None
            result = resp.json()
            status = result.get("status", "")
            if status == "Working":
                return None
            if status == "Fail":
                raise RuntimeError(f"CaptchaRun Turnstile 任务失败: {result.get('reason', 'unknown')}")
            response_obj = result.get("response", {})
            if not isinstance(response_obj, dict):
                return None
            token = response_obj.get("gRecaptchaResponse") or response_obj.get("token") or ""
            if not token:
                return None
            return token

        for _ in range(max_poll):
            await asyncio.sleep(poll_interval)
            token = await asyncio.to_thread(poll_once)
            if token:
                # 注入到页面 Turnstile widget
                if page is not None:
                    try:
                        await page.evaluate(
                            """(token) => {
                                const input = document.querySelector('input[name="cf-turnstile-response"]');
                                if (!input) return false;
                                const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
                                if (setter) setter.call(input, token); else input.value = token;
                                input.dispatchEvent(new Event('input', { bubbles: true }));
                                input.dispatchEvent(new Event('change', { bubbles: true }));
                                // 触发 Turnstile 回调（如果有）
                                const widget = document.querySelector('[data-sitekey]');
                                if (widget && typeof window.turnstile !== 'undefined') {
                                    try { window.turnstile.ready(() => {}); } catch {}
                                }
                                return true;
                            }""",
                            token,
                        )
                    except Exception:
                        pass
                return token
        return None


PROVIDER = CaptchaRunTurnstileProvider()