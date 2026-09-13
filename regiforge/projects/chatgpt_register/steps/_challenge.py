from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from urllib.parse import urlparse


async def page_has_cloudflare_challenge(page) -> bool:
    try:
        title = (await page.title() or "").strip().lower()
    except Exception:
        title = ""
    url = (page.url or "").lower()
    if "challenges.cloudflare.com" in url:
        return True
    try:
        return bool(
            await page.evaluate(
                """(titleHint) => {
                    const body = (document.body && (document.body.innerText || document.body.textContent) || '').toLowerCase();
                    const title = String(titleHint || document.title || '').toLowerCase();
                    const hasWidget = Boolean(document.querySelector(
                        'input[name="cf-turnstile-response"], iframe[src*="challenges.cloudflare.com"], iframe[src*="turnstile"], .cf-turnstile, #challenge-stage, #cf-challenge-running, [id*="cf-chl"], [class*="cf-challenge"]'
                    ));
                    const textHit = /正在进行安全验证|请验证您是真人|verify you are human|attention required|just a moment|checking your browser|请稍候/.test(body)
                        || /请稍候|just a moment|attention required|security check/.test(title);
                    return hasWidget || textHit;
                }""",
                title,
            )
        )
    except Exception:
        return "请稍候" in title or "just a moment" in title


async def page_has_otp_or_password(page) -> bool:
    try:
        return bool(
            await page.evaluate(
                """() => {
                    const visible = (node) => {
                        if (!node) return false;
                        const style = getComputedStyle(node);
                        const rect = node.getBoundingClientRect();
                        return style.display !== 'none' && style.visibility !== 'hidden'
                            && rect.width > 0 && rect.height > 0;
                    };
                    const inputs = Array.from(document.querySelectorAll('input')).filter(visible);
                    return inputs.some((el) => {
                        const text = [
                            el.name, el.id, el.autocomplete, el.placeholder,
                            el.getAttribute('aria-label'), el.getAttribute('data-testid'),
                        ].filter(Boolean).join(' ').toLowerCase();
                        const type = String(el.type || '').toLowerCase();
                        const inputmode = String(el.getAttribute('inputmode') || '').toLowerCase();
                        if (type === 'password') return true;
                        return el.name === 'code'
                            || el.autocomplete === 'one-time-code'
                            || /code|verification|验证码|otp|one-time/.test(text)
                            || type === 'tel'
                            || inputmode === 'numeric'
                            || inputmode === 'decimal';
                    });
                }"""
            )
        )
    except Exception:
        return False


async def _inject_turnstile_token(page, token: str, ctx: Any) -> None:
    """将 Turnstile token 注入到页面，多种方式尝试以覆盖不同场景。

    场景 A：页面上有 Turnstile 挂件（如 auth.openai.com 登录页）→ 写 cf-turnstile-response input + 触发回调
    场景 B：Cloudflare 全页挑战（5 秒盾）→ iframe 内注入 + 触发回调让页面自动跳转
    """
    # ── 场景 A：主文档注入 ──────────────────────────────────────
    try:
        result = await page.evaluate(
            """(token) => {
                let ok = false;
                // 1. 写入 cf-turnstile-response 隐藏 input
                const input = document.querySelector('input[name="cf-turnstile-response"]');
                if (input) {
                    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
                    if (setter) setter.call(input, token); else input.value = token;
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                    ok = true;
                }
                // 2. 触发 window.turnstile 全局回调
                if (typeof window.turnstile === 'object' && window.turnstile) {
                    // turnstile.render 的回调
                    const widgets = document.querySelectorAll('[data-sitekey]');
                    widgets.forEach(w => {
                        const cb = w._turnstileCallback || w.dataset.callback;
                        if (cb && typeof window[cb] === 'function') {
                            try { window[cb](token); } catch {}
                        }
                    });
                    // turnstile.getResponse / turnstile.execute 兜底
                    try {
                        const containers = document.querySelectorAll('.cf-turnstile');
                        containers.forEach(c => {
                            if (c.id && window.turnstile.getResponse) {
                                try { window.turnstile.getResponse(c.id); } catch {}
                            }
                        });
                    } catch {}
                }
                // 3. 全局 onTurnstileCallback
                if (typeof window.onTurnstileCallback === 'function') {
                    try { window.onTurnstileCallback(token); } catch {}
                }
                // 4. Cloudflare 全页挑战——提交 challenge form
                const form = document.querySelector('form[action*="challenge"]');
                if (form && input) {
                    try { form.submit(); } catch {}
                }
                // 5. 查找 turnstile callback 名称（OpenAI/Auth0 常用方式）
                const scripts = Array.from(document.querySelectorAll('script:not([src])'));
                for (const s of scripts) {
                    const m = (s.textContent || '').match(/turnstile\\.render\\([^)]*callback:\\s*['"]([\\w]+)['"]/);
                    if (m && typeof window[m[1]] === 'function') {
                        try { window[m[1]](token); } catch {}
                    }
                }
                return ok;
            }""",
            token,
        )
        if result:
            ctx.log("Turnstile token 已注入主文档")
        else:
            ctx.log("主文档无 cf-turnstile-response input，尝试 Cloudflare iframe 注入")
    except Exception as exc:
        ctx.log(f"主文档注入失败: {exc}")

    # ── 场景 B：Cloudflare challenge iframe 内注入 ─────────────
    for frame in page.frames:
        furl = (frame.url or "").lower()
        if "challenges.cloudflare.com" not in furl and "turnstile" not in furl:
            continue
        try:
            injected = await frame.evaluate(
                """(token) => {
                    const input = document.querySelector('input[name="cf-turnstile-response"]');
                    if (input) {
                        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
                        if (setter) setter.call(input, token); else input.value = token;
                        input.dispatchEvent(new Event('input', { bubbles: true }));
                        input.dispatchEvent(new Event('change', { bubbles: true }));
                        return true;
                    }
                    // 有些全页挑战的 iframe 里不是 turnstile input，而是隐藏 form
                    const form = document.querySelector('form');
                    if (form) {
                        const hidden = document.createElement('input');
                        hidden.type = 'hidden';
                        hidden.name = 'cf-turnstile-response';
                        hidden.value = token;
                        form.appendChild(hidden);
                        try { form.submit(); } catch {}
                        return true;
                    }
                    return false;
                }""",
                token,
            )
            if injected:
                ctx.log("Turnstile token 已注入 Cloudflare iframe")
        except Exception:
            continue


async def try_click_cloudflare_checkbox(page) -> bool:
    """尽量点击 CF 复选框；跨 iframe，失败则返回 False 交给人工。"""
    # 主文档内
    try:
        clicked = await page.evaluate(
            """() => {
                const labels = Array.from(document.querySelectorAll('label, span, div, input[type="checkbox"]'));
                const hit = labels.find((node) => {
                    const text = (node.innerText || node.textContent || node.getAttribute('aria-label') || '').toLowerCase();
                    return /验证您是真人|verify you are human|i am human/.test(text);
                });
                if (!hit) return false;
                hit.click();
                return true;
            }"""
        )
        if clicked:
            return True
    except Exception:
        pass

    # Cloudflare challenge iframe
    for frame in page.frames:
        furl = (frame.url or "").lower()
        if "challenges.cloudflare.com" not in furl and "turnstile" not in furl:
            continue
        try:
            box = frame.locator("input[type=checkbox], body")
            if await box.count():
                # 点 iframe 内常见复选区域
                target = frame.locator("input[type=checkbox]").first
                if await target.count():
                    await target.click(timeout=2000, force=True)
                    return True
                await frame.locator("body").click(position={"x": 30, "y": 30}, timeout=2000)
                return True
        except Exception:
            continue
    return False


async def wait_cloudflare_if_needed(
    page,
    ctx: Any,
    *,
    timeout: float = 180,
    captcha: Any | None = None,
) -> None:
    """若页面是 Cloudflare 安全验证，等待通过（可手动点「验证您是真人」）。"""
    if not await page_has_cloudflare_challenge(page):
        return

    deadline = time.monotonic() + max(30.0, timeout)
    ctx.log("检测到 Cloudflare 安全验证，请在浏览器窗口勾选「验证您是真人」")
    clicked = await try_click_cloudflare_checkbox(page)
    if clicked:
        ctx.log("已尝试自动点击 Cloudflare 复选框")

    # 根据配置的 captcha Provider 类型处理 Cloudflare 挑战
    if captcha is not None:
        try:
            captcha_id = getattr(captcha, "id", "")
            captcha_type = getattr(captcha, "type", "")
            if captcha_type == "cloudflare" and captcha_id == "captcharun":
                # Cloudflare 5 秒盾 → 走 CaptchaRun API 自动解决
                remaining = max(10.0, deadline - time.monotonic())
                ctx.log(f"使用 CaptchaRun CloudFlare5s 自动解决（最多 {int(remaining)}s）")
                # 使用 project.py 已获取的同一代理
                proxy_info = ctx.acquired_proxy
                if proxy_info and proxy_info.server:
                    parsed = urlparse(proxy_info.server)
                    proxy_host = parsed.hostname or ""
                    proxy_port = parsed.port or 0
                    proxy_login = proxy_info.username or ""
                    proxy_password = proxy_info.password or ""
                    result_json = await captcha.solve(
                        sitekey="",
                        page_url=page.url,
                        proxy_host=proxy_host,
                        proxy_port=proxy_port,
                        proxy_login=proxy_login,
                        proxy_password=proxy_password,
                    )
                    if result_json:
                        data = json.loads(result_json)
                        cf_clearance = data.get("cf_clearance", "")
                        ua = data.get("ua", "")
                        if cf_clearance:
                            domain = urlparse(page.url).hostname or ""
                            await page.context.add_cookies([
                                {
                                    "name": "cf_clearance",
                                    "value": cf_clearance,
                                    "domain": domain,
                                    "path": "/",
                                    "httpOnly": True,
                                    "secure": True,
                                    "sameSite": "Lax",
                                }
                            ])
                            ctx.log(f"已注入 cf_clearance Cookie（domain={domain}），正在刷新页面...")
                            # 设置 UA 后刷新页面
                            if ua:
                                await page.context.set_extra_http_headers({"User-Agent": ua})
                            try:
                                await page.reload(timeout=30_000)
                                await page.wait_for_load_state("networkidle", timeout=30_000)
                            except Exception:
                                pass
                            # 刷新后立即检查是否已通过
                            if not await page_has_cloudflare_challenge(page):
                                ctx.log("Cloudflare 5 秒盾已通过（CaptchaRun）")
                                return
                            ctx.log("CaptchaRun 注入后 Cloudflare 仍存在，回退到手动等待")
                else:
                    ctx.log("未获取到代理信息，无法使用 CaptchaRun CloudFlare5s，回退到手动模式")
            elif captcha_type == "turnstile":
                # Turnstile 类 provider（browser_manual / captcharun / capsolver）
                remaining = max(10.0, deadline - time.monotonic())
                provider_name = f"turnstile.{captcha_id}"
                ctx.log(f"使用 {provider_name} 等待 Turnstile 完成（最多 {int(remaining)}s）")

                # browser_manual 不走 API，直接在页面上等
                if captcha_id == "browser_manual":
                    try:
                        token = await captcha.solve(sitekey="", page_url=page.url, page=page, timeout=remaining)
                        if token:
                            ctx.log("Turnstile 已在浏览器中完成")
                            return
                    except Exception as exc:
                        ctx.log(f"Turnstile 手动等待异常: {exc}")
                else:
                    # API 类 provider（capsolver / captcharun）—— 调 API 获取 token 再注入
                    try:
                        token = await captcha.solve(sitekey="", page_url=page.url, page=page, timeout=remaining)
                        if token:
                            ctx.log(f"{provider_name} 已获取 Turnstile token（长度 {len(token)}），注入页面...")
                            await _inject_turnstile_token(page, token, ctx)

                            # 等待 Cloudflare 自动跳转
                            for _ in range(15):
                                await asyncio.sleep(1)
                                if not await page_has_cloudflare_challenge(page):
                                    ctx.log(f"Turnstile token 注入后 Cloudflare 已通过（{provider_name}）")
                                    return
                            ctx.log("Token 注入后 Cloudflare 仍存在，继续轮询")
                        else:
                            ctx.log(f"{provider_name} 未返回 token，继续手动等待")
                    except RuntimeError as exc:
                        if "sitekey" not in str(exc).lower():
                            raise
                        # sitekey 未找到 → 回退到 cloudflare.captcharun（如果有代理）
                        ctx.log("Turnstile sitekey 未找到，尝试 CloudFlare5s 方案")
                        proxy_info = ctx.acquired_proxy
                        if proxy_info and proxy_info.server:
                            try:
                                from captcha.cloudflare.captcharun.provider import PROVIDER as cf_provider
                                cf_provider._config = getattr(captcha, "_config", {})
                                parsed = urlparse(proxy_info.server)
                                result_json = await cf_provider.solve(
                                    sitekey="",
                                    page_url=page.url,
                                    proxy_host=parsed.hostname or "",
                                    proxy_port=parsed.port or 0,
                                    proxy_login=proxy_info.username or "",
                                    proxy_password=proxy_info.password or "",
                                )
                                if result_json:
                                    data = json.loads(result_json)
                                    cf_clearance = data.get("cf_clearance", "")
                                    ua = data.get("ua", "")
                                    if cf_clearance:
                                        domain = urlparse(page.url).hostname or ""
                                        await page.context.add_cookies([{
                                            "name": "cf_clearance", "value": cf_clearance,
                                            "domain": domain, "path": "/",
                                            "httpOnly": True, "secure": True, "sameSite": "Lax",
                                        }])
                                        ctx.log(f"CloudFlare5s 兜底：已注入 cf_clearance（domain={domain}）")
                                        if ua:
                                            await page.context.set_extra_http_headers({"User-Agent": ua})
                                        try:
                                            await page.reload(timeout=30_000)
                                            await page.wait_for_load_state("networkidle", timeout=30_000)
                                        except Exception:
                                            pass
                                        if not await page_has_cloudflare_challenge(page):
                                            ctx.log("CloudFlare5s 兜底方案已通过")
                                            return
                                        ctx.log("CloudFlare5s 注入后仍存在挑战，继续轮询")
                            except Exception as cf_exc:
                                ctx.log(f"CloudFlare5s 兜底失败: {cf_exc}")
                        else:
                            ctx.log("无代理信息，CloudFlare5s 兜底不可用，继续自动点击等待")
        except Exception as exc:
            # Provider 超时不直接失败，继续轮询页面状态（人工可能刚点完）
            ctx.log(f"Captcha Provider 未完成: {exc}")

    while time.monotonic() < deadline:
        if await page_has_otp_or_password(page):
            ctx.log("Cloudflare 已通过，出现 OTP/密码输入")
            return
        if not await page_has_cloudflare_challenge(page):
            # 中间跳转页也可能短暂无 challenge 文案
            try:
                title = (await page.title() or "").strip().lower()
            except Exception:
                title = ""
            if "请稍候" not in title and "just a moment" not in title:
                ctx.log("Cloudflare 页面已离开，继续后续步骤")
                return
        # 每 5 秒再尝试点一次复选框（含 iframe 内）
        if int(time.monotonic()) % 5 == 0:
            clicked = await try_click_cloudflare_checkbox(page)
            if clicked:
                ctx.log("自动点击 Cloudflare 复选框")
        await asyncio.sleep(1)

    screenshot = "data/chatgpt_cf_timeout.png"
    try:
        await page.screenshot(path=screenshot, full_page=True)
    except Exception:
        screenshot = "未能保存"
    raise RuntimeError(
        "Cloudflare 安全验证超时；请在有头浏览器中完成「验证您是真人」，"
        f"或改用可用 SOCKS5 代理后重试。截图={screenshot} url={page.url}"
    )
