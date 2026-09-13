from __future__ import annotations

import re

from ._state import RegistrationState


async def run(page, state: RegistrationState) -> str:
    await page.wait_for_timeout(1500)
    body = await page.locator("body").inner_text()
    match = re.search(r"sk_tr_[A-Za-z0-9]+", body)
    if not match:
        raise RuntimeError("TokenRhythm 注册成功页未找到 sk_tr_ API Key")
    state.api_key = match.group()
    return state.api_key
