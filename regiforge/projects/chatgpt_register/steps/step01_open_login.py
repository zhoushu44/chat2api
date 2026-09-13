from __future__ import annotations

import asyncio

from ._browser import click_by_text


LOGIN_URL = "https://chatgpt.com/auth/login"
AUTH_LOGIN_URL = "https://auth.openai.com/authorize"
EMAIL_INPUTS = (
    "#email",
    'input[type="email"]',
    'input[name="email"]',
    'input[autocomplete="email"]',
    'input[placeholder*="电子邮件"]',
    'input[placeholder*="email" i]',
)


async def _click_email_login_entry(page) -> bool:
    """只点击邮箱登录入口（排除 Google/Apple/Microsoft 等第三方登录按钮）。"""
    return bool(
        await page.evaluate(
            r"""() => {
                const visible = (node) => {
                    if (!node || node.disabled || node.getAttribute('aria-disabled') === 'true') return false;
                    const style = getComputedStyle(node);
                    const rect = node.getBoundingClientRect();
                    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                };
                const text = (node) => [node.innerText, node.textContent, node.value,
                    node.getAttribute('aria-label'), node.getAttribute('title')]
                    .filter(Boolean).join(' ').replace(/\s+/g, ' ').trim().toLowerCase();
                const nodes = Array.from(document.querySelectorAll(
                    'button, a, [role="button"], input[type="submit"]'
                )).filter(visible);
                // 排除第三方登录按钮（含 google/apple/microsoft/facebook 等）
                const isThirdParty = (t) => /google|apple|microsoft|facebook|github|sso|continue with (google|apple|microsoft|facebook)/.test(t);
                // 优先精确匹配 "Continue with email" / "使用邮箱继续"
                let hit = nodes.find((node) => {
                    const t = text(node);
                    if (isThirdParty(t)) return false;
                    return /continue with email|使用邮箱|邮箱继续|continue\s+with\s+email/.test(t);
                });
                if (!hit) {
                    // 次选：含 email/邮箱 字样且非第三方
                    hit = nodes.find((node) => {
                        const t = text(node);
                        if (isThirdParty(t)) return false;
                        return /\bemail\b|邮箱|电子邮件/.test(t);
                    });
                }
                if (!hit) {
                    // 再次：通用 "继续"/"continue" 但不含第三方品牌
                    hit = nodes.find((node) => {
                        const t = text(node);
                        if (isThirdParty(t)) return false;
                        return /^(继续|continue|下一步|next|sign\s*up|注册|登录|log\s*in|sign\s*in)$/.test(t)
                            || /^continue$/i.test(t);
                    });
                }
                if (!hit) return false;
                hit.focus();
                hit.click();
                return true;
            }"""
        )
    )


async def run(page, email: str = "") -> None:
    last_error: Exception | None = None
    email_locator = page.locator(", ".join(EMAIL_INPUTS))
    for attempt in range(1, 4):
        try:
            # 直接导航到 auth.openai.com 登录页（带邮箱参数）
            params = f"?email={email}" if email else ""
            await page.goto(f"{AUTH_LOGIN_URL}{params}", wait_until="commit", timeout=60_000)
            await page.wait_for_timeout(3000)
            if await email_locator.count():
                return
            # 兜底：打开 chatgpt.com 登录页
            await page.goto(LOGIN_URL, wait_until="commit", timeout=60_000)
            await page.wait_for_timeout(1500)

            if not await email_locator.count():
                await _click_email_login_entry(page)
                await page.wait_for_timeout(1200)

            if not await email_locator.count():
                await _click_email_login_entry(page)
                await page.wait_for_timeout(1000)

            await email_locator.first.wait_for(state="visible", timeout=30_000)
            return
        except Exception as exc:
            last_error = exc
            if page.is_closed():
                raise RuntimeError(
                    "ChatGPT 登录页在加载时被关闭；请保持自动打开的 Chrome 窗口"
                ) from exc
            if attempt < 3:
                await asyncio.sleep(attempt * 1.5)
    detail = str(last_error).strip() if last_error else "未知错误"
    raise RuntimeError(
        "ChatGPT 登录页连续 3 次打开失败；请检查网络或填写可用 SOCKS5 代理后重试。"
        f"最后错误: {detail}"
    ) from last_error
