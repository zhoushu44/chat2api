from __future__ import annotations

import asyncio

from core.base import SmsProvider

from ._state import RegistrationState


async def run(state: RegistrationState, sms: SmsProvider) -> str:
    state.phone = await asyncio.to_thread(sms.get_phone)
    if not state.phone:
        raise RuntimeError("短信 Provider 未返回手机号")
    return state.phone
