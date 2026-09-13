from __future__ import annotations

from core.base import CaptchaProvider


async def run(page, captcha: CaptchaProvider, timeout: float) -> str:
    result = await captcha.solve(
        sitekey="",
        page_url=page.url,
        page=page,
        timeout=timeout,
    )
    if not result:
        raise RuntimeError("阿里云 slider captcha 验证失败")
    return result
