from __future__ import annotations


async def run(page) -> None:
    button = page.get_by_role("button", name="发送验证码")
    await button.wait_for(state="visible", timeout=20_000)
    await button.click()
