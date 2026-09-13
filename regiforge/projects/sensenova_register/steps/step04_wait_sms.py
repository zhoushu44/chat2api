from __future__ import annotations

from core.base import SmsProvider

from ._engine import RegistrationState


async def run(state: RegistrationState, sms: SmsProvider, timeout: float) -> str:
    state.code = await sms.get_verify_code(state.phone, timeout=timeout) or ""
    if not state.code:
        raise TimeoutError(f"验证码获取超时 ({timeout}秒)")
    return state.code
