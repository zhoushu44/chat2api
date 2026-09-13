from __future__ import annotations

from core.base import RegistrationProject, RunContext
from core.browser_runner import browser_session, resolve_browser_backend
from core.models import AccountResult
from core.step_debug import RegisterDebug, status_for_class

from .steps import (
    step01_acquire_phone,
    step02_open_register,
    step03_send_code,
    step04_solve_captcha,
    step05_wait_sms,
    step06_submit_code,
    step07_accept_agreement,
    step08_submit_register,
    step09_fetch_apikey,
)
from .steps._state import RegistrationState


class TokenRhythmRegisterProject(RegistrationProject):
    id = "tokenrhythm_register"
    name = "基元律动 TokenRhythm"
    description = "有头浏览器手机号注册，自动处理阿里云滑块并提取 sk_tr_ API Key"
    required_captcha_types = ["slider"]

    async def run_one(self, ctx: RunContext) -> AccountResult:
        if not ctx.sms:
            return AccountResult(
                status="fail_no_sms",
                failed_step="init",
                failure_class="exception",
                error="该项目需要短信接码服务，但未选择 SMS Provider",
            )
        if not ctx.captcha:
            return AccountResult(
                status="fail_no_captcha",
                failed_step="init",
                failure_class="captcha_fail",
                error="该项目需要 slider.aliyun 验证码 Provider",
            )

        config = (ctx.config.get("projects") or {}).get(self.id) or {}
        sms_timeout = float(config.get("sms_timeout") or 120)
        captcha_timeout = float(config.get("captcha_timeout") or 30)
        browser_channel = str(config.get("browser_channel") or "chrome").strip()
        browser_backend = resolve_browser_backend(ctx.config, project_id=self.id)
        user_agent = str(config.get("user_agent") or "").strip()
        state = RegistrationState()
        dbg = RegisterDebug(ctx=ctx, project_id=self.id, email=f"sms:{ctx.sms.id}")
        proxy_info = await ctx.proxy.acquire()
        context = None
        page = None

        try:
            async with browser_session(
                proxy_info=proxy_info,
                browser_channel=browser_channel,
                browser_backend=browser_backend,
                user_agent=user_agent,
            ) as (context, page):
                await dbg.start_trace(context)
                steps = [
                    ("step01_acquire_phone", step01_acquire_phone.run, (state, ctx.sms)),
                    ("step02_open_register", step02_open_register.run, (page, state)),
                    ("step03_send_code", step03_send_code.run, (page,)),
                    ("step04_solve_captcha", step04_solve_captcha.run, (page, ctx.captcha, captcha_timeout)),
                    ("step05_wait_sms", step05_wait_sms.run, (state, ctx.sms, sms_timeout)),
                    ("step06_submit_code", step06_submit_code.run, (page, state)),
                    ("step07_accept_agreement", step07_accept_agreement.run, (page,)),
                    ("step08_submit_register", step08_submit_register.run, (page,)),
                    ("step09_fetch_apikey", step09_fetch_apikey.run, (page, state)),
                ]
                for step_id, fn, args in steps:
                    outcome = await dbg.run_step(page, step_id, fn, *args)
                    if not outcome.ok:
                        return await dbg.fail(
                            page,
                            context,
                            step_id=outcome.step_id,
                            status=status_for_class(outcome.failure_class, outcome.step_id),
                            error=outcome.error,
                            failure_class=outcome.failure_class,
                            email=state.phone,
                        )

                if not state.api_key.startswith("sk_tr_"):
                    return await dbg.fail(
                        page,
                        context,
                        step_id="step09_fetch_apikey",
                        status="fail_no_key",
                        error="提取到的 API Key 格式无效",
                        failure_class="unexpected_ui",
                        email=state.phone,
                    )
                await dbg.success_cleanup(context)
                return dbg.ok_result(
                    email=state.phone,
                    apikey=state.api_key,
                    extra={"phone": state.phone, "registered_via": "browser"},
                )
        except Exception as exc:
            return await dbg.fail(
                page,
                context,
                step_id=dbg.failed_step or "browser_session",
                status="fail_browser_session",
                error=f"{type(exc).__name__}: {exc}",
                email=state.phone,
            )
        finally:
            try:
                if state.phone:
                    await ctx.sms.release_phone(state.phone)
            finally:
                if proxy_info:
                    await ctx.proxy.release(proxy_info)


PROJECT = TokenRhythmRegisterProject()
