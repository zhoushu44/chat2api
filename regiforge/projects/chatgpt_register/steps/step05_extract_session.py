from __future__ import annotations

import asyncio
import time

from ._browser import click_by_text


def _is_navigation_interruption(exc: Exception) -> bool:
    message = str(exc).lower()
    return "execution context was destroyed" in message or "frame was detached" in message


def _on_chatgpt_main(url: str) -> bool:
    value = (url or "").lower()
    if "chatgpt.com" not in value:
        return False
    if any(x in value for x in ("auth.openai.com", "/auth/login", "/signup")):
        return False
    return True


async def _dismiss_onboarding(page) -> None:
    await click_by_text(
        page,
        (
            "跳过",
            "skip",
            "继续",
            "continue",
            "下一步",
            "next",
            "完成",
            "done",
            "开始",
            "get started",
            "okay",
            "ok",
            "got it",
        ),
    )


async def _read_session(page) -> dict:
    """读 /api/auth/session；对齐 oumiFree 的 accessToken / sessionToken。"""
    return await page.evaluate(
        """async () => {
            try {
                const response = await fetch('/api/auth/session', { credentials: 'include' });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) {
                    return { ok: false, error: `session http=${response.status}` };
                }
                const token = String(
                    data.accessToken
                    || data.access_token
                    || data.sessionToken
                    || data.session_token
                    || data.token
                    || ''
                );
                if (token) {
                    return {
                        ok: true,
                        token,
                        keys: Object.keys(data || {}),
                        has_access: Boolean(data.accessToken || data.access_token),
                        has_session: Boolean(data.sessionToken || data.session_token),
                    };
                }
                const keys = Object.keys(data || {});
                return {
                    ok: false,
                    error: `session http=200 no token; keys=[${keys.slice(0, 20).join(',')}]`,
                    keys,
                };
            } catch (error) {
                return { ok: false, error: String(error && error.message || error || 'session failed') };
            }
        }"""
    )


async def _read_cookie_token(page) -> str:
    try:
        return str(
            await page.evaluate(
                """() => {
                    const cookies = document.cookie.split(';').map(s => s.trim());
                    for (const item of cookies) {
                        const idx = item.indexOf('=');
                        if (idx < 0) continue;
                        const name = item.slice(0, idx).trim().toLowerCase();
                        const value = item.slice(idx + 1).trim();
                        if (!value || value.length < 20) continue;
                        if (name.includes('session') || name.includes('token') || name === '__secure-next-auth.session-token') {
                            return value;
                        }
                    }
                    return '';
                }"""
            )
            or ""
        )
    except Exception:
        return ""


async def _read_localstorage_token(page) -> str:
    try:
        result = await page.evaluate(
            """() => {
                try {
                    const ls = window.localStorage;
                    for (const key of Object.keys(ls)) {
                        const val = ls.getItem(key);
                        if (!val || val.length < 20 || val.length > 8000) continue;
                        try {
                            const parsed = JSON.parse(val);
                            const tok = parsed.accessToken || parsed.token || parsed.access_token
                                || parsed.sessionToken || parsed.session_token;
                            if (tok && String(tok).length > 20) return String(tok);
                        } catch (_) {}
                        if (val.startsWith('eyJ')) return val;
                    }
                } catch (_) {}
                return '';
            }"""
        )
        return str(result or "")
    except Exception:
        return ""


async def run(page, ctx, *, timeout: float = 120) -> str:
    deadline = time.monotonic() + timeout
    last_error = ""

    while time.monotonic() < deadline:
        try:
            await _dismiss_onboarding(page)
            current = (page.url or "").lower()

            # 仍停在 about-you：账号未创建完成，不能硬跳主站
            if "about-you" in current or "create-account" in current:
                last_error = f"仍在资料页: {page.url}"
                ctx.log(last_error)
                await asyncio.sleep(2)
                continue

            if "email-verification" in current:
                last_error = f"仍在邮箱验证页: {page.url}"
                ctx.log(last_error)
                await asyncio.sleep(2)
                continue

            # 对齐 oumiFree [8/9]：确保进入 chatgpt.com 后再读 session
            if not _on_chatgpt_main(current):
                try:
                    ctx.log(f"当前不在 chatgpt.com 主站（{current}），正在导航...")
                    await page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=60_000)
                    ctx.log("导航完成，等待页面稳定...")
                    await page.wait_for_timeout(2500)
                except Exception as exc:
                    last_error = str(exc)
                    await asyncio.sleep(2)
                    continue
            else:
                try:
                    await page.wait_for_load_state("networkidle", timeout=20_000)
                except Exception:
                    pass
                await page.wait_for_timeout(1200)

            await _dismiss_onboarding(page)
            try:
                await page.evaluate(
                    """() => {
                        const btns = document.querySelectorAll('button');
                        btns.forEach(b => {
                            const t = (b.textContent || '').toLowerCase().trim();
                            if (['accept', 'accept all', '同意', '确认', 'ok', 'got it', 'continue', 'dismiss', 'skip', '跳过'].includes(t)) {
                                b.click();
                            }
                        });
                    }"""
                )
            except Exception:
                pass

            result = await _read_session(page)
            if result and result.get("ok") and result.get("token"):
                kind = "accessToken" if result.get("has_access") else "sessionToken/other"
                ctx.log(f"Session 已就绪（{kind}）")
                return str(result["token"])

            last_error = str((result or {}).get("error") or "no accessToken")
            ctx.log(f"session 尚未就绪: {last_error}")

            # 备用：localStorage / cookie
            alt = await _read_localstorage_token(page)
            if alt:
                ctx.log("从 localStorage 找到备用 token")
                return alt
            cookie_tok = await _read_cookie_token(page)
            if cookie_tok and cookie_tok.startswith("eyJ"):
                ctx.log("从 cookie 找到备用 token")
                return cookie_tok

            # WARNING_BANNER 时刷新一次主站
            if "WARNING_BANNER" in last_error or "no token" in last_error:
                try:
                    await page.reload(wait_until="domcontentloaded", timeout=45_000)
                    await page.wait_for_timeout(2000)
                except Exception:
                    pass

        except Exception as exc:
            last_error = str(exc)
            if _is_navigation_interruption(exc):
                ctx.log("页面正在跳转，等待稳定后重试读取 Session")
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=15_000)
                except Exception:
                    pass
                await asyncio.sleep(1.5)
                continue
        await asyncio.sleep(2)

    raise RuntimeError(f"等待 Session Token 超时；最后错误: {last_error or 'unknown'}")
