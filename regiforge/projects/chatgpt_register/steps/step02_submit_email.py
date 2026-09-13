from __future__ import annotations

import asyncio
import re
from urllib.parse import quote

from .step01_open_login import AUTH_LOGIN_URL, EMAIL_INPUTS
from ._challenge import page_has_cloudflare_challenge, page_has_otp_or_password


def _still_on_email_gate(url: str) -> bool:
    """仍停在「登录或注册」邮箱入口页（尚未进入 OTP/密码/授权流）。"""
    value = (url or "").lower()
    if not value:
        return True
    # Chrome 网络错误页（代理掉线等）→ 视为仍在入口
    if value.startswith("chrome-error://") or "chromewebdata" in value:
        return True
    # 第三方登录页（Google/Apple/Microsoft 等）说明误点了第三方按钮，不算"已提交邮箱"
    if any(host in value for host in ("accounts.google.com", "appleid.apple.com", "login.microsoftonline.com", "facebook.com")):
        return True
    # 已进入验证码/密码/创建账号/授权回调，视为已离开邮箱入口
    left_markers = (
        "password",
        "email-verification",
        "email-otp",
        "otp",
        "create-account",
        "about-you",
        "callback",
        "auth.openai.com/log-in",
        "auth.openai.com/u/",
    )
    if any(marker in value for marker in left_markers):
        return False
    # chatgpt.com/auth/login 或仅有邮箱预填的 authorize 入口仍算未提交
    if "chatgpt.com/auth/login" in value:
        return True
    if "auth.openai.com" in value and "email=" in value and "password" not in value:
        return True
    if re.search(r"auth\.openai\.com/?($|\?)", value):
        return True
    return False


async def _page_session_expired(page) -> bool:
    """检测 OpenAI 会话是否已过期（页面标题/正文含"会话已结束"）。"""
    try:
        title = (await page.title() or "").strip().lower()
    except Exception:
        title = ""
    if "会话已结束" in title or "session has ended" in title or "session expired" in title:
        return True
    try:
        return bool(
            await page.evaluate(
                """() => {
                    const body = (document.body && (document.body.innerText || document.body.textContent) || '').toLowerCase();
                    return /会话已结束|session.{0,5}end|session.{0,5}expir/.test(body);
                }"""
            )
        )
    except Exception:
        return False


async def _page_looks_post_email(page) -> bool:
    """DOM 侧判断：是否已离开邮箱入口（OTP/密码/CF 挑战都算提交成功）。"""
    # 会话过期不算"提交成功"——页面虽无邮箱框但也不是目标页
    if await _page_session_expired(page):
        return False
    # 第三方登录页（Google/Apple/Microsoft 等）说明误点了第三方按钮，不算"已提交邮箱"
    current_url = (page.url or "").lower()
    if any(host in current_url for host in ("accounts.google.com", "appleid.apple.com", "login.microsoftonline.com", "facebook.com")):
        return False
    if await page_has_cloudflare_challenge(page):
        return True
    if await page_has_otp_or_password(page):
        return True
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
                    const stillEmailGate = inputs.some((el) => {
                        const type = String(el.type || '').toLowerCase();
                        const text = [
                            el.name, el.id, el.autocomplete, el.placeholder,
                            el.getAttribute('aria-label'),
                        ].filter(Boolean).join(' ').toLowerCase();
                        return type === 'email' || /email|电子邮件|邮箱/.test(text);
                    });
                    // 已无邮箱框，视为离开入口
                    return !stillEmailGate;
                }"""
            )
        )
    except Exception:
        return False


async def _email_is_confirmed(page, email: str) -> bool:
    """确认可见邮箱框已真正写入本轮邮箱。"""
    try:
        return bool(
            await page.evaluate(
                """(email) => {
                    const visible = (node) => {
                        if (!node) return false;
                        const style = getComputedStyle(node);
                        const rect = node.getBoundingClientRect();
                        return style.display !== 'none' && style.visibility !== 'hidden'
                            && rect.width > 0 && rect.height > 0;
                    };
                    return Array.from(document.querySelectorAll('input')).some((el) => {
                        const hint = [el.type, el.name, el.id, el.autocomplete, el.placeholder]
                            .filter(Boolean).join(' ').toLowerCase();
                        return visible(el) && (el.type === 'email' || /email|邮箱|电子邮件/.test(hint))
                            && String(el.value || '').trim().toLowerCase() === String(email).trim().toLowerCase();
                    });
                }""",
                email,
            )
        )
    except Exception:
        return False


async def _click_email_form_submit(page, email: str) -> bool:
    """只提交已填邮箱所属的表单，避免点到第三方登录或其它通用按钮。"""
    return bool(
        await page.evaluate(
            """(email) => {
                const visible = (node) => {
                    if (!node || node.disabled || node.getAttribute('aria-disabled') === 'true') return false;
                    const style = getComputedStyle(node);
                    const rect = node.getBoundingClientRect();
                    return style.display !== 'none' && style.visibility !== 'hidden'
                        && rect.width > 0 && rect.height > 0;
                };
                const input = Array.from(document.querySelectorAll('input')).find((el) => {
                    const hint = [el.type, el.name, el.id, el.autocomplete, el.placeholder]
                        .filter(Boolean).join(' ').toLowerCase();
                    return visible(el) && (el.type === 'email' || /email|邮箱|电子邮件/.test(hint))
                        && String(el.value || '').trim().toLowerCase() === String(email).trim().toLowerCase();
                });
                if (!input) return false;
                const text = (node) => (node.innerText || node.textContent || node.value || '')
                    .replace(/\\s+/g, ' ').trim().toLowerCase();
                // 排除第三方登录按钮（google/apple/microsoft/facebook/github/sso 单点登录）
                const isThirdParty = (t) => /\\bgoogle\\b|\\bapple\\b|\\bmicrosoft\\b|\\bfacebook\\b|\\bgithub\\b|\\bsso\\b|continue with (google|apple|microsoft|facebook|github)/.test(t);
                // 1) 优先：邮箱框所在 form 的 type=submit 按钮
                let form = input.closest('form');
                if (form) {
                    const submitBtns = Array.from(form.querySelectorAll('button[type="submit"], input[type="submit"]')).filter(visible);
                    if (submitBtns.length > 0) {
                        const safe = submitBtns.find((b) => !isThirdParty(text(b))) || submitBtns[0];
                        safe.focus();
                        safe.click();
                        return true;
                    }
                    // form 内含 "继续/continue" 文本的按钮（排除第三方）
                    const candidates = Array.from(form.querySelectorAll('button, [role="button"]')).filter(visible)
                        .filter((b) => !isThirdParty(text(b)));
                    const continueBtn = candidates.find((b) => /^(继续|continue|下一步|next|sign\\s*up|注册)$/.test(text(b)));
                    if (continueBtn) {
                        continueBtn.focus();
                        continueBtn.click();
                        return true;
                    }
                }
                // 2) 兜底：从邮箱框向上找最近容器，其中的 submit/continue 按钮（排除第三方）
                const selector = 'button, input[type="submit"], [role="button"]';
                let container = form;
                if (!container) {
                    for (let node = input.parentElement; node && node !== document.body; node = node.parentElement) {
                        const candidates = Array.from(node.querySelectorAll(selector)).filter(visible)
                            .filter((item) => !isThirdParty(text(item)));
                        if (candidates.some((item) => /(继续|continue|下一步|next|sign\\s*up|注册)/.test(text(item)))) {
                            container = node;
                            break;
                        }
                    }
                }
                if (!container) return false;
                const nodes = Array.from(container.querySelectorAll(selector)).filter(visible)
                    .filter((node) => !isThirdParty(text(node)));
                const submit = nodes.find((node) => node.matches('button[type="submit"], input[type="submit"]'))
                    || nodes.find((node) => /^(继续|continue|下一步|next|sign\\s*up|注册)$/.test(text(node)));
                if (!submit) return false;
                submit.focus();
                submit.click();
                return true;
            }""",
            email,
        )
    )


async def run(page, email: str, *, _recovery_attempt: int = 0, ctx=None) -> None:
    # 先处理可能存在的 Cloudflare 挑战（IPDeep 等低信誉代理容易触发）
    if ctx is not None:
        from ._challenge import wait_cloudflare_if_needed, page_has_cloudflare_challenge
        # 调试：记录 step02 开始时的页面状态
        try:
            title = (await page.title() or "").strip()
            ctx.log(f"step02 页面状态: url={page.url} title={title!r}")
            cf_detected = await page_has_cloudflare_challenge(page)
            if cf_detected:
                ctx.log("step02 检测到 Cloudflare，开始处理...")
        except Exception:
            pass
        try:
            await wait_cloudflare_if_needed(
                page, ctx, timeout=90,
                captcha=getattr(ctx, "captcha", None),
            )
        except Exception as exc:
            ctx.log(f"step02 Cloudflare 处理异常（继续）: {exc}")

    joined = ", ".join(EMAIL_INPUTS)
    locator = page.locator(joined)
    # 增加等待前的调试信息
    try:
        if ctx is not None:
            title2 = (await page.title() or "").strip()
            ctx.log(f"等待邮箱输入框: url={page.url} title={title2!r}")
    except Exception:
        pass
    await locator.first.wait_for(state="visible", timeout=60_000)
    count = await locator.count()
    filled = False
    target = None
    for idx in range(count):
        item = locator.nth(idx)
        if await item.is_visible() and await item.is_enabled():
            await item.click()
            await item.fill("")
            await item.fill(email)
            await item.dispatch_event("input")
            await item.dispatch_event("change")
            # 触发 React controlled input 的原生 setter
            await page.evaluate(
                """(value) => {
                    const el = document.activeElement;
                    if (!(el instanceof HTMLInputElement)) return;
                    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
                    if (setter) setter.call(el, value);
                    el.dispatchEvent(new InputEvent('input', {bubbles: true, data: value, inputType: 'insertText'}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                }""",
                email,
            )
            target = item
            filled = True
            break
    if not filled:
        raise RuntimeError(f"未找到可填写邮箱输入框: {joined}")
    if not await _email_is_confirmed(page, email):
        raise RuntimeError("邮箱未能写入登录表单；已停止提交以避免误点其它登录按钮")

    # 等待 React 启用「继续」按钮
    await asyncio.sleep(1.0)

    for attempt in range(1, 20):
        if (not _still_on_email_gate(page.url)) or await _page_looks_post_email(page):
            return

        # Chrome 网络错误页（代理掉线等）→ 立即重新导航
        cur_url = (page.url or "").lower()
        if cur_url.startswith("chrome-error://") or "chromewebdata" in cur_url:
            if _recovery_attempt >= 2:
                raise RuntimeError(f"代理掉线导致页面错误，重试 {_recovery_attempt} 次仍无法恢复")
            ctx.log(f"step02: 检测到页面错误（{page.url}），重新导航到登录页") if ctx else None
            try:
                await page.goto(
                    f"{AUTH_LOGIN_URL}?email={quote(email, safe='@')}",
                    wait_until="commit",
                    timeout=60_000,
                )
                await page.wait_for_timeout(3000)
                return await run(page, email, _recovery_attempt=_recovery_attempt + 1, ctx=ctx)
            except Exception as exc:
                if ctx:
                    ctx.log(f"step02: 重新导航失败: {exc}")
                raise RuntimeError(f"代理掉线后重新导航失败: {exc}")

        # 检测会话过期 → 重新导航到带邮箱的授权入口
        if await _page_session_expired(page):
            if _recovery_attempt >= 2:
                raise RuntimeError(
                    f"OpenAI 会话已过期，重试 { _recovery_attempt} 次仍无法恢复: url={page.url!r}"
                )
            try:
                import sys
                print(f"[step02] 检测到会话过期，重新导航（第{_recovery_attempt+1}次）", file=sys.stderr, flush=True)
            except Exception:
                pass
            await page.goto(
                f"{AUTH_LOGIN_URL}?email={quote(email, safe='@')}",
                wait_until="commit",
                timeout=60_000,
            )
            await page.wait_for_timeout(2000)
            return await run(page, email, _recovery_attempt=_recovery_attempt + 1)

        # 检测是否误跳到第三方登录页（Google/Apple/Microsoft 等）
        current_url = (page.url or "").lower()
        if any(host in current_url for host in ("accounts.google.com", "appleid.apple.com", "login.microsoftonline.com", "facebook.com")):
            ctx_log_msg = f"检测到误跳第三方登录页（{page.url}），导航回授权入口"
            try:
                # 通过日志输出
                import sys
                print(f"[step02] {ctx_log_msg}", file=sys.stderr, flush=True)
            except Exception:
                pass
            try:
                await page.goto(
                    f"{AUTH_LOGIN_URL}?email={quote(email, safe='@')}",
                    wait_until="commit",
                    timeout=60_000,
                )
                await page.wait_for_timeout(2000)
                # 重新等待邮箱框出现并填写
                await locator.first.wait_for(state="visible", timeout=30_000)
                for idx in range(await locator.count()):
                    item = locator.nth(idx)
                    if await item.is_visible() and await item.is_enabled():
                        await item.click()
                        await item.fill("")
                        await item.fill(email)
                        await item.dispatch_event("input")
                        await item.dispatch_event("change")
                        target = item
                        break
                await asyncio.sleep(1.0)
            except Exception:
                pass

        # 只点击当前邮箱输入框所属表单的提交按钮。
        try:
            if await _click_email_form_submit(page, email):
                await asyncio.sleep(1.5)
                if (not _still_on_email_gate(page.url)) or await _page_looks_post_email(page):
                    return
        except Exception:
            pass
        
        # 如果提交后仍停留在邮箱页，尝试直接点击 Continue 按钮触发验证码
        try:
            continue_btn = page.locator('button:has-text("Continue"), button:has-text("继续"), button:has-text("Next")').first
            if await continue_btn.is_visible(timeout=2000) and await continue_btn.is_enabled():
                ctx.log("检测到 Continue 按钮，尝试点击触发验证码...")
                await continue_btn.click()
                await asyncio.sleep(2.0)
                if (not _still_on_email_gate(page.url)) or await _page_looks_post_email(page):
                    return
        except Exception:
            pass
        
        # 检查邮箱框是否为空（OpenAI 可能清空邮箱要求重新输入）
        try:
            email_input = page.locator('input[type="email"]').first
            if await email_input.is_visible(timeout=2000):
                current_value = await email_input.input_value()
                if not current_value or current_value.strip() == "":
                    ctx.log(f"邮箱框为空，重新填入 {email}")
                    await email_input.fill("")
                    await email_input.fill(email)
                    await email_input.press("Enter")
                    await asyncio.sleep(2.0)
                    if (not _still_on_email_gate(page.url)) or await _page_looks_post_email(page):
                        return
        except Exception:
            pass
        
        # 方式 2: 在邮箱框按 Enter（仅在仍停在邮箱入口时；避免触发默认表单跳到第三方）
        try:
            current_url2 = (page.url or "").lower()
            if (target is not None
                and "auth.openai.com" in current_url2
                and not any(host in current_url2 for host in ("accounts.google.com", "appleid.apple.com", "login.microsoftonline.com", "facebook.com"))):
                await target.press("Enter")
                await asyncio.sleep(1.2)
                if (not _still_on_email_gate(page.url)) or await _page_looks_post_email(page):
                    return
        except Exception:
            pass

        # 授权站偶尔会把已提交的邮箱重新带回空的 chatgpt.com 登录页。
        # 此时不能持续点击同一个失效页面；重新打开一次带邮箱的授权入口再填写。
        if attempt == 8 and _recovery_attempt < 1:
            try:
                await page.goto(
                    f"{AUTH_LOGIN_URL}?email={quote(email, safe='@')}",
                    wait_until="commit",
                    timeout=60_000,
                )
                await page.wait_for_timeout(1500)
                return await run(page, email, _recovery_attempt=_recovery_attempt + 1, ctx=ctx)
            except Exception:
                pass

        await asyncio.sleep(0.5)

    # 最后再等一会儿，给慢网络跳转
    for _ in range(30):
        if (not _still_on_email_gate(page.url)) or await _page_looks_post_email(page):
            return
        await asyncio.sleep(1)

    raise RuntimeError(
        f"提交邮箱后仍停在入口页: url={page.url!r}；请检查页面是否需要人机验证/代理"
    )
