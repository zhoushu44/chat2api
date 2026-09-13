from __future__ import annotations

import asyncio

from core.base import CaptchaProvider

from ._engine import RegistrationState


async def run(state: RegistrationState, region_code: str, captcha: CaptchaProvider | None) -> str:
    data = await asyncio.to_thread(state.client.send_sms, state.phone, region_code)
    if state.client.token_code:
        return state.client.token_code
    if captcha is None:
        raise RuntimeError("SenseNova 要求滑块验证码，但未选择 slider.sensenova Provider")
    code_key = await captcha.solve(
        sitekey="sensenova-slider",
        page_url="https://platform.sensenova.cn",
        session=state.client.session,
        proxies=state.client.proxies,
        iam_base=state.client.IAM_BASE,
    )
    if not code_key:
        raise RuntimeError(f"滑块验证码识别失败: {data}")
    data = await asyncio.to_thread(state.client.send_sms, state.phone, region_code, code_key)
    if not state.client.token_code:
        raise RuntimeError(f"发送验证码失败: {data}")
    return state.client.token_code
