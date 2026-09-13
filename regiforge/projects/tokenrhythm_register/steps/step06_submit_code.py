from __future__ import annotations

from ._state import RegistrationState


async def run(page, state: RegistrationState) -> None:
    code_input = page.locator('input[placeholder="请输入验证码"]')
    await code_input.wait_for(state="visible", timeout=20_000)
    await code_input.fill(state.sms_code)
