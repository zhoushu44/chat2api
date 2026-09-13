from __future__ import annotations

from typing import Any

from core.base import CaptchaProvider


class BrowserManualTurnstileProvider(CaptchaProvider):
    """Wait for Turnstile to complete in the site's own browser page.

    This provider does not manufacture, inject, or replay challenge tokens.  It
    only observes the response created by the Turnstile widget.  In headed mode
    the operator can complete an interactive challenge in the browser window.
    """

    type = "turnstile"
    id = "browser_manual"
    name = "浏览器内完成（Turnstile）"

    async def solve(self, *, sitekey: str, page_url: str, **kwargs: Any) -> str | None:
        page = kwargs.get("page")
        timeout = float(kwargs.get("timeout") or 180)
        if page is None:
            raise ValueError("turnstile.browser_manual 需要传入 Playwright page")

        present = await page.evaluate(
            """() => Boolean(document.querySelector(
                'input[name="cf-turnstile-response"], iframe[src*="turnstile"], .cf-turnstile, [data-sitekey], script[src*="turnstile"]'
            ))"""
        )
        if not present:
            await page.wait_for_timeout(1500)
            present = await page.evaluate(
                """() => Boolean(document.querySelector(
                    'input[name="cf-turnstile-response"], iframe[src*="turnstile"], .cf-turnstile, [data-sitekey], script[src*="turnstile"]'
                ))"""
            )
        if not present:
            return "browser-complete"

        await page.wait_for_function(
            """() => {
                const input = document.querySelector('input[name="cf-turnstile-response"]');
                const widget = document.querySelector(
                    'iframe[src*="turnstile"], .cf-turnstile, [data-sitekey], script[src*="turnstile"]'
                );
                return Boolean(input && String(input.value || '').trim().length >= 20);
            }""",
            timeout=timeout * 1000,
        )
        return await page.evaluate(
            """() => {
                const input = document.querySelector('input[name="cf-turnstile-response"]');
                return input ? String(input.value || '').trim() : 'browser-complete';
            }"""
        )


PROVIDER = BrowserManualTurnstileProvider()
