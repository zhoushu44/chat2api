from __future__ import annotations

from ._state import RegistrationState

REGISTER_URL = "https://tokenrhythm.studio/register"


async def run(page, state: RegistrationState) -> None:
    await page.goto(REGISTER_URL, wait_until="domcontentloaded", timeout=60_000)
    phone_input = page.locator('input[placeholder="请输入手机号"]')
    await phone_input.wait_for(state="visible", timeout=30_000)
    await phone_input.fill(state.phone)
