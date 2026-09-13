"""step01：打开 Z.ai OAuth 授权页并切入注册表单。"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

OAUTH_URL = (
    "https://chat.z.ai/auth?response_type=code"
    "&client_id=client_P8X5CMWmlaRO9gyO-KSqtg"
    "&redirect_uri=https%3A%2F%2Fzcode.z.ai%2Fapp%2Foauth%2Flogin%3Fredirect%3Dzcode%253A%252F%252Foauth%252Fcallback"
    "&state=6a8146b01fae09f641c8b8d8685876e51526fded4923daca0231fac360c7745e"
)

# 第三方追踪域：SOCKS5 上游并发连接上限有限，拦截这些无助于注册的请求，
# 减少浏览器并行连接数，避免主文档被饿死导致导航超时。
TRACKER_HOSTS = (
    "doubleclick.net",
    "googlesyndication.com",
    "google-analytics.com",
    "googletagmanager.com",
    "reddit.com",
    "twitter.com",
    "facebook.net",
    "facebook.com",
    "t.co",
)


async def _block_trackers(page: Any) -> None:
    async def _handler(route: Any) -> None:
        try:
            host = urlparse(route.request.url).netloc.lower()
        except Exception:  # noqa: BLE001
            host = ""
        if any(h in host for h in TRACKER_HOSTS):
            await route.abort()
            return
        try:
            await route.continue_()
        except Exception:  # noqa: BLE001
            pass

    await page.route("**/*", _handler)


async def run(page: Any) -> bool:
    await _block_trackers(page)
    # 并发/网络抖动时连接可能被断（ERR_CONNECTION_CLOSED），goto 用 commit + 重试
    last_err: Exception | None = None
    for _attempt in range(3):
        try:
            await page.goto(OAUTH_URL, wait_until="commit", timeout=45_000)
            await page.wait_for_selector("input[name=email]", timeout=30_000)
            break
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            await page.wait_for_timeout(3000)
    else:
        raise last_err  # type: ignore[misc]
    # 切到注册表单：JS 直点「注册」（Playwright click 偶尔被遮挡但返回成功）
    await page.evaluate(
        """() => {
            const t = [...document.querySelectorAll('button')].find(b =>
                (b.textContent || '').trim() === '注册' && !!(b.offsetWidth || b.offsetHeight));
            if (t) t.click();
        }"""
    )
    await page.wait_for_timeout(2500)
    try:
        await page.locator("input[name=new-password]").wait_for(timeout=15_000)
    except Exception:
        # 兜底：再试一次 Playwright 点击「注册」
        btn = page.get_by_role("button", name="注册").first
        try:
            await btn.click(timeout=5000)
        except Exception:
            pass
        await page.locator("input[name=new-password]").wait_for(timeout=15_000)
    return True
