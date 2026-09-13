from __future__ import annotations

import asyncio
import time

from ._challenge import wait_cloudflare_if_needed
from .step02_submit_email import _still_on_email_gate, _page_looks_post_email


async def _wait_code_input(page, ctx, timeout: float = 60) -> bool:
    """等待验证码输入框；如果出现密码页则返回 False 表示跳过验证码。"""
    deadline = time.monotonic() + timeout
    session_expired_count = 0
    page_refreshed = False
    while time.monotonic() < deadline:
        # 检查是否进入了密码页（验证码已完成）
        url = (page.url or "").lower()
        # `?email=` 仅表示登录页已带入邮箱，不代表已经完成验证码；
        # 只有真正进入密码或建号页时才跳过 OTP。
        if "password" in url or "create-account" in url:
            ctx.log(f"检测到密码/账号页（{url}），跳过验证码")
            return False
        # 检测会话过期——页面标题含"会话已结束"
        try:
            title = (await page.title() or "").strip().lower()
            if "会话已结束" in title or "session has ended" in title or "session expired" in title:
                session_expired_count += 1
                ctx.log(f"检测到会话过期（第{session_expired_count}次），等待页面恢复...")
                if session_expired_count >= 3:
                    raise RuntimeError("OpenAI 会话已过期，验证码页面不可用")
        except RuntimeError:
            raise
        except Exception:
            pass
        try:
            found = await page.evaluate(
                """() => {
                    const visible = (node) => {
                        if (!node) return false;
                        const style = getComputedStyle(node);
                        const rect = node.getBoundingClientRect();
                        return style.display !== 'none' && style.visibility !== 'hidden'
                            && rect.width > 0 && rect.height > 0;
                    };
                    const nodes = Array.from(document.querySelectorAll('input')).filter(visible);
                    return nodes.some((el) => {
                        const text = [
                            el.name, el.id, el.autocomplete, el.placeholder,
                            el.getAttribute('aria-label'), el.getAttribute('data-testid'),
                        ].filter(Boolean).join(' ').toLowerCase();
                        const type = String(el.type || '').toLowerCase();
                        const inputmode = String(el.getAttribute('inputmode') || '').toLowerCase();
                        return el.name === 'code'
                            || el.autocomplete === 'one-time-code'
                            || /code|verification|验证码|otp|one-time/.test(text)
                            || type === 'tel'
                            || inputmode === 'numeric'
                            || inputmode === 'decimal';
                    });
                }"""
            )
            if found:
                return True
        except Exception as exc:
            if page.is_closed():
                raise RuntimeError("等待验证码时浏览器页面已关闭") from exc
            if "Execution context was destroyed" not in str(exc):
                raise
        # 超时 60 秒未检测到验证码框时，尝试刷新页面重新触发
        elapsed = deadline - time.monotonic()
        if not page_refreshed and elapsed < timeout - 60 and elapsed > 30:
            try:
                ctx.log("验证码框等待超过 30 秒，尝试刷新页面重新触发验证码...")
                await page.reload(wait_until="commit", timeout=30000)
                await asyncio.sleep(3)
                page_refreshed = True
            except Exception as exc:
                ctx.log(f"刷新页面失败：{exc}，继续等待")
        await asyncio.sleep(1)
    # 超时前最后尝试检测一次页面状态
    try:
        title = await page.title()
        ctx.log(f"超时前最后检测：url={page.url}, title={title!r}")
    except Exception:
        pass
    raise RuntimeError("等待验证码输入框超时")


async def _fill_code(page, code: str) -> None:
    # 优先用 Playwright 原生 fill 逐格输入，触发 React 事件
    all_inputs = page.locator("input")
    code_inputs = []
    for idx in range(await all_inputs.count()):
        item = all_inputs.nth(idx)
        if await item.is_visible() and await item.is_enabled():
            if await item.get_attribute("maxlength") == "1":
                code_inputs.append(item)
    if len(code_inputs) >= len(code):
        for box, ch in zip(code_inputs, code):
            await box.fill(ch)
        return
    # 兜底：用 evaluate 填 aggregate 输入框
    state = await page.evaluate(
        """(code) => {
            const visible = (node) => {
                const s = getComputedStyle(node); const r = node.getBoundingClientRect();
                return !node.disabled && !node.readOnly && s.display !== 'none' &&
                    s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
            };
            const setValue = (node, value) => {
                const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
                if (setter) setter.call(node, value); else node.value = value;
                node.dispatchEvent(new InputEvent('input', {bubbles: true, data: value}));
                node.dispatchEvent(new Event('change', {bubbles: true}));
            };
            const labelText = (el) => [
                el.name, el.id, el.autocomplete, el.placeholder,
                el.getAttribute('aria-label'), el.getAttribute('data-testid'),
            ].filter(Boolean).join(' ').toLowerCase();
            const all = Array.from(document.querySelectorAll('input')).filter(visible);
            const aggregate = all.find((node) =>
                node.name === 'code'
                || node.autocomplete === 'one-time-code'
                || /code|verification|验证码|otp|one-time/.test(labelText(node))
                || Number(node.maxLength || 0) >= 4
            ) || all.find((node) => {
                const type = String(node.type || '').toLowerCase();
                const inputmode = String(node.getAttribute('inputmode') || '').toLowerCase();
                return !String(node.value || '').includes('@')
                    && (type === 'tel' || inputmode === 'numeric' || inputmode === 'decimal');
            });
            if (aggregate) { aggregate.focus(); setValue(aggregate, code); return 'aggregate'; }
            return null;
        }""",
        code,
    )
    if state:
        return
    # 最后兜底：填所有可见输入框
    all_inputs = page.locator("input:visible")
    cnt = await all_inputs.count()
    for i in range(min(cnt, len(code))):
        try:
            await all_inputs.nth(i).fill(code[i])
        except Exception:
            pass
    raise RuntimeError("验证码已收到，但页面上未找到 OTP 输入框")


async def _resubmit_email_if_needed(page, ctx, email: str) -> None:
    """step02 可能误判成功（页面加载过渡期邮箱框暂时消失），step03 开始时检查
    是否仍在邮箱入口页。如果是，尝试重新点击「继续」提交邮箱。"""
    from urllib.parse import quote
    for attempt in range(3):
        if not _still_on_email_gate(page.url):
            return
        if await _page_looks_post_email(page):
            await asyncio.sleep(2)
            if not _still_on_email_gate(page.url):
                return
        ctx.log(f"step03: 仍在邮箱入口页（{page.url}），尝试重新提交邮箱（第{attempt+1}次）")
        try:
            # 确认邮箱框有值
            email_input = page.locator('input[type="email"]').first
            try:
                if await email_input.is_visible(timeout=2000):
                    current_value = await email_input.input_value()
                    if not current_value or current_value.strip().lower() != email.lower():
                        await email_input.fill("")
                        await email_input.fill(email)
                        await asyncio.sleep(0.5)
            except Exception:
                pass

            # 方法 1：点击「继续」按钮（用 evaluate 精确定位非第三方登录按钮）
            clicked = await page.evaluate(
                """(email) => {
                    const visible = (node) => {
                        if (!node || node.disabled || node.getAttribute('aria-disabled') === 'true') return false;
                        const s = getComputedStyle(node); const r = node.getBoundingClientRect();
                        return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                    };
                    const isThirdParty = (t) => /\\bgoogle\\b|\\bapple\\b|\\bmicrosoft\\b|\\bfacebook\\b|\\bgithub\\b|\\bphone\\b|电话/.test(t);
                    const btns = Array.from(document.querySelectorAll('button, [role="button"]')).filter(visible)
                        .filter((b) => !isThirdParty((b.innerText || b.textContent || '').toLowerCase()));
                    const continueBtn = btns.find((b) => /^(继续|continue|下一步|next)$/.test((b.innerText || b.textContent || '').trim().toLowerCase()));
                    if (continueBtn) { continueBtn.click(); return true; }
                    return false;
                }""",
                email,
            )
            if clicked:
                ctx.log("step03: 已点击「继续」按钮（evaluate）")
                await asyncio.sleep(3)
                if not _still_on_email_gate(page.url):
                    return
                if await _page_looks_post_email(page):
                    await asyncio.sleep(2)
                    if not _still_on_email_gate(page.url):
                        return

            # 方法 2：在邮箱框按 Enter
            try:
                await email_input.press("Enter")
                ctx.log("step03: 已在邮箱框按 Enter")
                await asyncio.sleep(3)
                if not _still_on_email_gate(page.url):
                    return
            except Exception:
                pass

            # 方法 3：直接调用 ChatGPT signin API（绕过 React 表单）
            try:
                api_result = await page.evaluate(
                    """async (email) => {
                        try {
                            // 1. 获取 CSRF token
                            const csrfResp = await fetch('https://chatgpt.com/api/auth/csrf', {
                                method: 'GET',
                                credentials: 'include',
                            });
                            const csrfData = await csrfResp.json();
                            const csrfToken = csrfData.csrfToken || '';
                            if (!csrfToken) return { ok: false, error: 'csrfToken empty' };

                            // 2. 提交邮箱
                            const params = new URLSearchParams({
                                prompt: 'login',
                                'ext-oai-did': '',
                                screen_hint: 'login_or_signup',
                                login_hint: email,
                            });
                            const signinResp = await fetch(
                                'https://chatgpt.com/api/auth/signin/openai?' + params.toString(),
                                {
                                    method: 'POST',
                                    credentials: 'include',
                                    headers: {
                                        'Content-Type': 'application/x-www-form-urlencoded',
                                    },
                                    body: 'csrfToken=' + encodeURIComponent(csrfToken),
                                    redirect: 'manual',
                                }
                            );
                            const location = signinResp.headers.get('location') || '';
                            const status = signinResp.status;
                            return { ok: status === 302 || status === 200, status, location, csrf: csrfToken.slice(0, 8) };
                        } catch (e) {
                            return { ok: false, error: String(e && e.message || e) };
                        }
                    }""",
                    email,
                )
                ctx.log(
                    f"step03: signin API → ok={api_result.get('ok')} status={api_result.get('status')} "
                    f"location={str(api_result.get('location') or '')[:80]} err={api_result.get('error') or ''}"
                )
                # 如果 API 返回了重定向 URL，跟随它
                location = str(api_result.get("location") or "")
                if location:
                    if location.startswith("/"):
                        location = f"https://chatgpt.com{location}"
                    try:
                        await page.goto(location, wait_until="commit", timeout=30_000)
                        await page.wait_for_timeout(2000)
                    except Exception as exc:
                        ctx.log(f"step03: 跟随 signin 重定向失败: {exc}")
                if not _still_on_email_gate(page.url):
                    return
                if await _page_looks_post_email(page):
                    await asyncio.sleep(2)
                    if not _still_on_email_gate(page.url):
                        return
            except Exception as exc:
                ctx.log(f"step03: signin API 调用失败: {exc}")

        except Exception as exc:
            ctx.log(f"step03: 重新提交邮箱失败: {exc}")
        await asyncio.sleep(2)


async def run(page, ctx, email: str, timeout: float = 180) -> str | None:
    # 提交邮箱后常见 Cloudflare 拦截，先等人工/自动通过
    await wait_cloudflare_if_needed(
        page,
        ctx,
        timeout=max(90.0, float(timeout)),
        captcha=getattr(ctx, "captcha", None),
    )
    # step02 可能误判成功——页面仍在邮箱入口时重新提交
    await _resubmit_email_if_needed(page, ctx, email)
    try:
        needs_code = await _wait_code_input(page, ctx, timeout=max(90.0, float(timeout)))
    except RuntimeError as exc:
        if "等待验证码输入框超时" not in str(exc):
            raise
        screenshot = "data/chatgpt_otp_timeout.png"
        try:
            await page.screenshot(path=screenshot, full_page=True)
        except Exception:
            screenshot = "未能保存"
        title = ""
        try:
            title = await page.title()
        except Exception:
            pass
        ctx.log(f"未检测到验证码框，url={page.url} title={title!r} 截图={screenshot}")
        raise
    if not needs_code:
        ctx.log("验证码已完成，跳过验证码输入")
        return None
    ctx.log(f"验证码页已出现，开始通过邮箱 Provider 收取 {email} 验证码")
    code = await ctx.email.wait_code(email, timeout=timeout)
    if not code:
        raise RuntimeError(f"等待 {email} 的邮箱验证码超时")
    clean = str(code).replace("-", "").strip()
    await _fill_code(page, clean)
    ctx.log(f"验证码 {clean[:2]}**** 已填入，等待提交后导航...")
    # 截图 debug：验证码页状态
    try:
        await page.screenshot(path="data/chatgpt_otp_filled.png", full_page=True)
    except Exception:
        pass
    # 直接点击 Continue 按钮
    before = page.url
    ctx.log(f"验证码提交前页面: {before}")
    # 等待 Continue 按钮变为 enabled（验证码填入后 React 需要一帧来启用）
    try:
        continue_btn = page.locator('button:has-text("Continue"), button:has-text("继续"), button:has-text("验证"), button:has-text("Verify")').first
        await continue_btn.wait_for(state="visible", timeout=10_000)
        # 显式等 enabled，最多 8 秒
        for _ in range(16):
            if await continue_btn.is_enabled():
                break
            await asyncio.sleep(0.5)
        ctx.log("Continue 按钮已 enabled，准备点击")
    except Exception as exc:
        ctx.log(f"等待 Continue 按钮 enabled 失败: {exc}")
    for submit_attempt in range(1, 30):
        # 调试：打印可见按钮
        try:
            debug_btns = await page.evaluate(
                """() => Array.from(document.querySelectorAll('button')).filter(b => {
                    const s = getComputedStyle(b); const r = b.getBoundingClientRect();
                    return s.display !== 'none' && r.width > 0;
                }).map(b => b.textContent.trim().slice(0, 30)).join(' | ')"""
            )
            if debug_btns and submit_attempt % 5 == 1:
                ctx.log(f"可见按钮: {debug_btns}")
        except Exception:
            pass
        # 1) 直接点击 "Continue" 按钮（不区分大小写）
        try:
            btn = page.locator('button:has-text("Continue"), button:has-text("继续"), button:has-text("验证"), button:has-text("Verify")').first
            if await btn.is_visible(timeout=300):
                await btn.click()
                await asyncio.sleep(1.0)
                if page.url != before and "verification" not in (page.url or "").lower():
                    ctx.log("验证码提交后已导航离开")
                    break
        except Exception:
            pass
        # 2) Enter 键
        try:
            await page.keyboard.press("Enter")
            await asyncio.sleep(0.8)
            if page.url != before and "verification" not in (page.url or "").lower():
                break
        except Exception:
            pass
        # 3) 触发表单提交
        try:
            await page.evaluate(
                """() => {
                    const form = document.querySelector('form');
                    if (form) { if (form.requestSubmit) form.requestSubmit(); else form.submit(); }
                }"""
            )
            await asyncio.sleep(0.8)
            if page.url != before and "verification" not in (page.url or "").lower():
                break
        except Exception:
            pass
        # 4) 点所有可见按钮（兜底）
        try:
            await page.evaluate(
                """() => {
                    const btns = Array.from(document.querySelectorAll('button, [role="button"]')).filter(b => {
                        const s = getComputedStyle(b);
                        const r = b.getBoundingClientRect();
                        return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                    });
                    if (btns.length > 0) btns[0].click();
                }"""
            )
            await asyncio.sleep(0.8)
            if page.url != before and "verification" not in (page.url or "").lower():
                break
        except Exception:
            pass
        # 5) 检查是否已自动导航
        if page.url != before and "verification" not in (page.url or "").lower():
            break
        # 6) 对齐 oumiFree：UI 卡住时直接调 email-otp/validate
        if submit_attempt in (3, 8, 15):
            try:
                api_result = await page.evaluate(
                    """async (code) => {
                        try {
                            const response = await fetch('https://auth.openai.com/api/accounts/email-otp/validate', {
                                method: 'POST',
                                credentials: 'include',
                                headers: {
                                    'Content-Type': 'application/json',
                                    'Accept': 'application/json',
                                    'Origin': 'https://auth.openai.com',
                                    'Referer': location.href,
                                },
                                body: JSON.stringify({ code }),
                            });
                            const text = await response.text();
                            let data = {};
                            try { data = JSON.parse(text); } catch (_) { data = { raw: text.slice(0, 200) }; }
                            return {
                                ok: response.ok,
                                status: response.status,
                                continue_url: data.continue_url || data.continueUrl || '',
                                data,
                            };
                        } catch (error) {
                            return { ok: false, status: 0, error: String(error && error.message || error) };
                        }
                    }""",
                    clean,
                )
                ctx.log(
                    f"email-otp/validate: ok={api_result.get('ok')} status={api_result.get('status')} "
                    f"continue={str(api_result.get('continue_url') or '')[:100]} err={api_result.get('error') or ''}"
                )
                if api_result.get("ok"):
                    continue_url = str(api_result.get("continue_url") or "")
                    if continue_url:
                        if continue_url.startswith("/"):
                            continue_url = f"https://auth.openai.com{continue_url}"
                        try:
                            await page.goto(continue_url, wait_until="commit", timeout=60_000)
                            await page.wait_for_timeout(1500)
                        except Exception as exc:
                            ctx.log(f"跟随 OTP continue_url 失败: {exc}")
                    if "verification" not in (page.url or "").lower():
                        ctx.log(f"验证码 API 提交后页面: {page.url}")
                        break
            except Exception as exc:
                ctx.log(f"email-otp/validate 调用失败: {exc}")
    # 等页面稳定
    try:
        await page.wait_for_load_state("networkidle", timeout=30_000)
    except Exception:
        pass
    await page.wait_for_timeout(2000)
    return clean
