from __future__ import annotations

import asyncio

from ._engine import RegistrationState


async def run(state: RegistrationState) -> dict:
    response = await asyncio.to_thread(state.client.verify_sms, state.code)
    if response.get("code") != 1 and "access_token" not in str(response):
        raise RuntimeError(f"验证码校验失败: {response}")
    return response
