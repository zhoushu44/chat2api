from __future__ import annotations

import asyncio

from ._engine import RegistrationState, generate_password, generate_username


async def run(state: RegistrationState) -> str:
    state.username = generate_username()
    state.password = generate_password()
    state.redirect_url = await asyncio.to_thread(state.client.register, state.username, state.password)
    return state.redirect_url
