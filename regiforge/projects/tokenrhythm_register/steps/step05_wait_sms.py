from __future__ import annotations

from core.base import SmsProvider

from ._state import RegistrationState


async def run(state: RegistrationState, sms: SmsProvider, timeout: float) -> str:
    state.sms_code = await sms.get_verify_code(state.phone, timeout=timeout) or ""
    if not state.sms_code:
        raise TimeoutError("短信验证码等待超时")
    return state.sms_code
