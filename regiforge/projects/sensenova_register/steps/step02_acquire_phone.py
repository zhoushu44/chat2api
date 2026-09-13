from __future__ import annotations

import asyncio

from core.base import SmsProvider

from ._engine import RegistrationState


async def run(state: RegistrationState, sms: SmsProvider) -> str:
    state.phone = await asyncio.to_thread(sms.get_phone)
    return state.phone
