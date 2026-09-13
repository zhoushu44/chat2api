from __future__ import annotations

import asyncio

from core.base import RegistrationProject, RunContext
from core.browser_runner import browser_session, resolve_browser_backend
from core.models import AccountResult
from core.step_debug import RegisterDebug, status_for_class

from .steps import (
    step01_open_oauth,
    step02_fill_register,
    step03_submit_captcha,
    step04_verify_email,
    step05_finalize_register,
    step06_extract_token,
)


class ZcodeRegisterProject(RegistrationProject):
    id = "zcode_register"
    name = "ZCode / Z.ai"
    description = (
        "Z.ai OAuth 直注册：用户名+邮箱+密码 → 阿里云滑块（yydsocr + 非线性映射）→ "
        "邮箱验证链接 → 设置密码完成注册；产出 accessToken"
    )
    required_captcha_types: list[str] = ["slider"]

    async def run_one(self, ctx: RunContext) -> AccountResult:
        email = await asyncio.to_thread(ctx.email.generate_address)
        project_cfg = (ctx.config.get("projects") or {}).get(self.id) or {}
        mail_timeout = float(project_cfg.get("mail_timeout") or 180)
        captcha_timeout = float(project_cfg.get("captcha_timeout") or 90)
        browser_backend = resolve_browser_backend(ctx.config, project_id=self.id)

        proxy_info = await ctx.proxy.acquire()
        ctx.log(f"开始 ZCode 注册，邮箱：{email}")
        ctx.log(f"浏览器底座：{browser_backend}")

        dbg = RegisterDebug(ctx=ctx, project_id=self.id, email=email)
        ctx.log(f"证据目录：{dbg.evidence_dir}")
        context = None
        page = None
        try:
            async with browser_session(
                proxy_info=proxy_info,
                browser_backend=browser_backend,
            ) as (context, page):
                await dbg.start_trace(context)
                ctx.log("浏览器已启动（有头模式）")

                state: dict = {}
                steps = [
                    ("step01_open_oauth", lambda: step01_open_oauth.run(page)),
                    ("step02_fill_register", lambda: step02_fill_register.run(page, email)),
                    (
                        "step03_submit_captcha",
                        lambda: step03_submit_captcha.run(page, ctx, timeout=captcha_timeout),
                    ),
                    (
                        "step04_verify_email",
                        lambda: step04_verify_email.run(page, ctx, email, timeout=mail_timeout),
                    ),
                    (
                        "step05_finalize_register",
                        lambda: step05_finalize_register.run(page, state.get("password") or ""),
                    ),
                    ("step06_extract_token", lambda: step06_extract_token.run(page)),
                ]

                token = ""
                user_id = ""
                for step_id, step_fn in steps:
                    outcome = await dbg.run_step(page, step_id, step_fn, false_is_fail=False)
                    if not outcome.ok:
                        return await dbg.fail(
                            page,
                            context,
                            step_id=step_id,
                            status=status_for_class(outcome.failure_class, step_id),
                            error=outcome.error,
                            failure_class=outcome.failure_class,
                        )
                    if step_id == "step02_fill_register":
                        state.update(outcome.value or {})
                        ctx.log(f"用户名：{state.get('name')}")
                    elif step_id == "step03_submit_captcha":
                        ctx.log("表单已提交，进入邮箱验证")
                    elif step_id == "step06_extract_token":
                        value = outcome.value or {}
                        token = value.get("token") if isinstance(value, dict) else (value or "")
                        user_id = value.get("user_id") if isinstance(value, dict) else ""

                await dbg.success_cleanup(context)
                ctx.log("注册完成")
                return dbg.ok_result(
                    apikey=token,
                    status="ok" if token else "no_key",
                    extra={"source_type": "web", "user_id": user_id},
                )
        except Exception as exc:
            return await dbg.fail(
                page,
                context,
                step_id=dbg.failed_step or "run_browser",
                status="fail_exception",
                error=str(exc),
                failure_class="exception",
            )


PROJECT = ZcodeRegisterProject()
