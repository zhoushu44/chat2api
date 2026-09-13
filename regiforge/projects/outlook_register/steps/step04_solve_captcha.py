"""step04：通过 Microsoft 按压验证码（funcaptcha.browser_press）。

对应外部仓库 patchright_controller.handle_captcha 的调用点：
- 已到「让我们来保护你的帐户」/ #EmailAddress → 无需验证码
- 出现 iframe#enforcementFrame（图片 FunCaptcha，非按压）→ 无法自动通过
- 出现 iframe[title="验证质询"] → 调 ctx.captcha（funcaptcha.browser_press）按压
"""
from __future__ import annotations

import time
from typing import Any


async def run(page: Any, ctx: Any, humanizer: Any, max_retries: int = 3) -> bool:
    if await _passed(page):
        return True

    if await page.locator("iframe#enforcementFrame").count() > 0:
        raise RuntimeError("出现 FunCaptcha 图片验证（非按压类型），无法自动通过 (captcha)")

    # 等待按压验证码 iframe 出现（最多 15s）
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if await page.locator('iframe[title="验证质询"]').count() > 0:
            break
        if await _passed(page):
            return True
        await page.wait_for_timeout(500)
    else:
        raise RuntimeError("未检测到按压验证码且未进入下一步 (captcha)")

    ctx.log("出现按压验证码，调用 funcaptcha.browser_press 处理")
    result = await ctx.captcha.solve(
        sitekey="",
        page_url=page.url,
        page=page,
        humanizer=humanizer,
        max_retries=max_retries,
    )
    if not result:
        raise RuntimeError("FunCaptcha 按压验证未通过（达到最大重试次数）(captcha)")
    ctx.log("按压验证码已通过")
    return True


async def _passed(page: Any) -> bool:
    try:
        if await page.get_by_text("让我们来保护你的帐户").count() > 0:
            return True
        if await page.locator("#EmailAddress").count() > 0:
            return True
    except Exception:
        pass
    return False
