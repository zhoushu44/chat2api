from __future__ import annotations

import asyncio

from ._engine import RegistrationState


async def run(state: RegistrationState) -> str:
    keys = await asyncio.to_thread(state.client.get_api_keys)
    if not keys:
        keys = [await asyncio.to_thread(state.client.create_api_key)]
    state.api_key = keys[0].get("api_key", "")
    state.api_key_name = keys[0].get("displayname", "")
    if not state.api_key:
        raise RuntimeError("未返回 API Key")
    state.user_info = await asyncio.to_thread(state.client.get_user_info)
    return state.api_key
