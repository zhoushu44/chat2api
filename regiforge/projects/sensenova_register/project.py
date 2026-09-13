from __future__ import annotations

from core.base import RegistrationProject, RunContext
from core.models import AccountResult
from core.step_debug import RegisterDebug, StepOutcome

from .steps import (
    step01_oauth_challenge,
    step02_acquire_phone,
    step03_send_sms,
    step04_wait_sms,
    step05_verify_sms,
    step06_register,
    step07_exchange_token,
    step08_fetch_apikey,
)
from .steps._engine import RegistrationState, SensenovaClient


class SensenovaRegisterProject(RegistrationProject):
    id = "sensenova_register"
    name = "商汤 SenseNova"
    description = "OAuth2 PKCE HTTP 注册，复用 SMS、验证码和代理 Provider，产出 API Key"
    required_captcha_types = ["slider"]

    async def run_one(self, ctx: RunContext) -> AccountResult:
        project_cfg = (ctx.config.get("projects") or {}).get(self.id) or {}
        sms_timeout = float(project_cfg.get("sms_timeout") or 120)
        retry_count = max(1, int(project_cfg.get("retry_count") or 3))
        region_code = str(project_cfg.get("region_code") or "86")
        user_agent = str(project_cfg.get("user_agent") or "").strip()

        if not ctx.sms:
            return AccountResult(
                status="fail_no_sms", failed_step="init", failure_class="exception",
                error="该项目需要短信接码服务，但未选择 SMS Provider",
            )

        dbg = RegisterDebug(ctx=ctx, project_id=self.id, email=f"sms:{ctx.sms.id}")
        proxy_info = await ctx.proxy.acquire()
        proxy_url = proxy_info.server if proxy_info else ""
        state: RegistrationState | None = None

        ctx.log("开始商汤 SenseNova 注册")
        ctx.log(f"代理: {proxy_url or '直连'}")

        try:
            for attempt in range(1, retry_count + 1):
                ctx.log(f"注册尝试 {attempt}/{retry_count}")
                state = RegistrationState(SensenovaClient(proxy=proxy_url or None, user_agent=user_agent))
                outcome = await self._run_attempt(
                    dbg, state, ctx, region_code=region_code, sms_timeout=sms_timeout,
                )
                if outcome.ok:
                    break
                if state.phone:
                    await ctx.sms.release_phone(state.phone)
                if attempt < retry_count:
                    delay = min(10 * attempt, 30)
                    if "operationTooFrequently" in (outcome.error or ""):
                        delay = max(delay, 30)
                    ctx.log(f"步骤 {outcome.step_id} 失败（{outcome.failure_class}），{delay}秒后从 OAuth challenge 重新注册")
                    import asyncio as _aio
                    await _aio.sleep(delay)
                    continue
                return await self._fail(dbg, outcome, state)
            else:
                return await self._fail(dbg, outcome, state)

            assert state is not None
            ctx.log(f"API Key 已取得（长度 {len(state.api_key)}）")
            return dbg.ok_result(
                email=state.phone,
                apikey=state.api_key,
                status="ok",
                extra={
                    "username": state.username,
                    "phone": state.phone,
                    "user_id": state.client.user_id,
                    "tenant_code": state.user_info.get("tenant_code", state.username),
                    "access_token": state.client.access_token,
                    "refresh_token": state.client.refresh_token,
                    "registered_via": "http",
                },
            )
        finally:
            if proxy_info:
                await ctx.proxy.release(proxy_info)

    async def _run_attempt(
        self,
        dbg: RegisterDebug,
        state: RegistrationState,
        ctx: RunContext,
        *,
        region_code: str,
        sms_timeout: float,
    ) -> StepOutcome:
        steps = [
            ("step01_oauth_challenge", step01_oauth_challenge.run, (state,)),
            ("step02_acquire_phone", step02_acquire_phone.run, (state, ctx.sms)),
            ("step03_send_sms", step03_send_sms.run, (state, region_code, ctx.captcha)),
            ("step04_wait_sms", step04_wait_sms.run, (state, ctx.sms, sms_timeout)),
            ("step05_verify_sms", step05_verify_sms.run, (state,)),
            ("step06_register", step06_register.run, (state,)),
            ("step07_exchange_token", step07_exchange_token.run, (state, ctx.sms)),
            ("step08_fetch_apikey", step08_fetch_apikey.run, (state,)),
        ]
        outcome: StepOutcome | None = None
        for step_id, fn, args in steps:
            outcome = await dbg.run_step(None, step_id, fn, *args)
            if not outcome.ok:
                return outcome
        assert outcome is not None
        return outcome

    async def _fail(
        self,
        dbg: RegisterDebug,
        outcome: StepOutcome,
        state: RegistrationState | None,
    ) -> AccountResult:
        return await dbg.fail(
            None,
            None,
            step_id=outcome.step_id,
            status=f"fail_{outcome.step_id}",
            error=outcome.error,
            failure_class=outcome.failure_class,
            email=state.phone if state else None,
        )


PROJECT = SensenovaRegisterProject()
