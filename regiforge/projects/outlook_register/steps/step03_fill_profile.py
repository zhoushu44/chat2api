"""step03：填写姓名（lastname/firstname）并提交，进入验证阶段。

对应外部仓库 base_controller.outlook_register：
  等待 #lastNameInput / #firstNameInput → 填写 → 保证总操作时长 ≥ bot_protection_wait
  → 提交 → 等待条款链接脱离（表单提交成功）→ 检查风控文本。
"""
from __future__ import annotations

import time
from typing import Any

TERMS_LINK = 'span > [href="https://go.microsoft.com/fwlink/?LinkID=521839"]'


async def run(
    page: Any,
    humanizer: Any,
    *,
    person: dict,
    state: dict,
    bot_protection_wait: float = 16.0,
) -> bool:
    lname_input = page.locator("#lastNameInput")
    await lname_input.wait_for(state="visible", timeout=8000)
    await humanizer.smooth_type(lname_input, person["lastname"])

    await humanizer.wait_ratio(0.02)
    fname_input = page.locator("#firstNameInput")
    await fname_input.wait_for(state="visible", timeout=8000)
    await humanizer.smooth_type(fname_input, person["firstname"])

    # 保证从 step01 开始的总操作时长 >= bot_protection_wait（模拟真人节奏）
    elapsed = time.monotonic() - (state.get("t0") or time.monotonic())
    if elapsed < bot_protection_wait:
        await page.wait_for_timeout(int((bot_protection_wait - elapsed) * 1000))

    primary_btn = page.locator('[data-testid="primaryButton"]').first
    await humanizer.smooth_click(primary_btn)

    # 条款链接脱离 = 表单已提交；22s 内未脱离则判定为风控/异常
    try:
        await page.locator(TERMS_LINK).wait_for(state="detached", timeout=22000)
    except Exception:
        if not await _next_phase(page):
            raise RuntimeError("资料提交后未进入验证阶段（疑似 IP 风控）(blocked_cf)")
    await page.wait_for_timeout(400)

    if await _rate_limited(page):
        raise RuntimeError("当前 IP 注册频率过快，被微软风控拦截（blocked_cf）")

    if await page.locator("iframe#enforcementFrame").count() > 0:
        # 出现 FunCaptcha 按压验证码，交由 step04 处理
        pass
    return True


async def _next_phase(page: Any) -> bool:
    """表单提交后的下一阶段标志：辅助邮箱 / 保护你的帐户 / 验证码 / 邮箱主界面。"""
    try:
        if await page.locator("#EmailAddress").count() > 0:
            return True
        if await page.get_by_text("让我们来保护你的帐户").count() > 0:
            return True
        if await page.locator("iframe#enforcementFrame").count() > 0:
            return True
        if await page.locator('[aria-label="新邮件"]').count() > 0:
            return True
    except Exception:
        pass
    return False


async def _rate_limited(page: Any) -> bool:
    try:
        if await page.get_by_text("一些异常活动").count() > 0:
            return True
        if await page.get_by_text("此站点正在维护，暂时无法使用，请稍后重试。").count() > 0:
            return True
    except Exception:
        pass
    return False
