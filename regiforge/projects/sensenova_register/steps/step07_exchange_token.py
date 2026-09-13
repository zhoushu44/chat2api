from __future__ import annotations

import asyncio

from core.base import SmsProvider

from ._engine import RegistrationState


async def run(state: RegistrationState, sms: SmsProvider) -> dict:
    await sms.release_phone(state.phone)
    return await asyncio.to_thread(state.client.exchange_code_for_token, state.redirect_url)
