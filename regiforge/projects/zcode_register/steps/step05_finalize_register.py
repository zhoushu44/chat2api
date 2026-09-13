"""step05：邮箱验证后的「完成注册」表单：填密码 + 确认密码，点完成注册。"""
from __future__ import annotations

from typing import Any


async def run(page: Any, password: str) -> bool:
    pw_inputs = page.locator("input[type=password]")
    n = await pw_inputs.count()
    if n >= 2:
        await pw_inputs.nth(0).fill(password)
        await pw_inputs.nth(1).fill(password)
    else:
        for placeholder in ("密码", "确认密码"):
            el = page.get_by_placeholder(placeholder).first
            if await el.count():
                await el.fill(password)
    # 用户名/邮箱未预填则补齐
    name_input = page.get_by_placeholder("用户名").first
    if await name_input.count() and not (await name_input.input_value()):
        await name_input.fill("zuser")
    email_input = page.get_by_placeholder("电子邮箱").first
    if await email_input.count() and not (await email_input.input_value()):
        raise RuntimeError("完成注册表单缺少电子邮箱预填值")

    try:
        await page.get_by_role("button", name="完成注册").first.click(timeout=8000)
    except Exception:
        await page.evaluate(
            """() => {
                const t = [...document.querySelectorAll('button')].find(b =>
                    (b.textContent || '').trim() === '完成注册' && !!(b.offsetWidth || b.offsetHeight));
                if (t) t.click();
            }"""
        )
    # 等待跳转：OAuth 回跳 / 应用页 / 主界面
    for _ in range(30):
        await page.wait_for_timeout(2000)
        url = page.url
        if "zcode" in url or "code=" in url or "app" in url or "/chat" in url or "chat.z.ai/" in url:
            return True
    return False
