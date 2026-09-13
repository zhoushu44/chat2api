from __future__ import annotations

import asyncio

from ._engine import RegistrationState


async def run(state: RegistrationState) -> str:
    challenge = await asyncio.to_thread(state.client.fetch_login_challenge)
    if not await asyncio.to_thread(state.client.check_challenge):
        raise RuntimeError("challenge 无效，请重试")
    return challenge
