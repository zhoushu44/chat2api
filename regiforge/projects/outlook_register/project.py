"""Outlook / Hotmail 注册项目：有头浏览器全链路。

迁移自外部仓库 `OutlookRegister`（base_controller.outlook_register +
patchright_controller.handle_captcha），按 RegiForge 规范接入：
- 浏览器：core.browser_runner.browser_session（playwright / patchright）
- 验证码：captcha/funcaptcha/browser_press（浏览器内按压挑战）
- 辅助邮箱：ctx.email（email.tempmail 收 Microsoft 安全代码）
- 代理：ctx.proxy
产出：email@outlook.com : password（凭证槽位 apikey）+ 辅助邮箱
"""
from __future__ import annotations

import time
from typing import Any

from core.base import RegistrationProject, RunContext
from core.browser_runner import browser_session, resolve_browser_backend
from core.models import AccountResult
from core.step_debug import RegisterDebug, status_for_class

from .steps import (
    step01_open_create,
    step02_fill_account,
    step03_fill_profile,
    step04_solve_captcha,
    step05_bind_recovery,
    step06_oauth_token,
)
from .steps._ms_utils import Humanizer, generate_strong_password, random_email_alias, random_person


class OutlookRegisterProject(RegistrationProject):
    id = "outlook_register"
    name = "Outlook / Hotmail"
    description = (
        "注册 outlook.com / hotmail.com 账号：有头浏览器模拟真人填表（邮箱别名+密码+生日+姓名）"
        "→ Microsoft 按压验证码 → 绑定辅助邮箱收安全代码；产出 账号:密码"
    )
    required_captcha_types = ["funcaptcha"]

    async def run_one(self, ctx: RunContext) -> AccountResult:
        project_cfg = (ctx.config.get("projects") or {}).get(self.id) or {}
        email_suffix = str(project_cfg.get("email_suffix") or "@outlook.com").strip()
        if not email_suffix.startswith("@"):
            email_suffix = f"@{email_suffix}"
        mail_timeout = float(project_cfg.get("mail_timeout") or 180)
        bot_wait = float(project_cfg.get("bot_protection_wait") or 16)
        max_captcha_retries = max(1, int(project_cfg.get("max_captcha_retries") or 3))
        browser_backend = resolve_browser_backend(ctx.config, project_id=self.id)

        if ctx.email is None:
            return AccountResult(
                status="fail_no_email",
                failed_step="init",
                failure_class="exception",
                error="Outlook 注册需要辅助邮箱 Provider（email.tempmail）接收安全代码，请先在控制台选择邮箱",
            )

        alias = random_email_alias()
        password = generate_strong_password()
        person = random_person()
        full_email = f"{alias}{email_suffix}"

        # OAuth (step06) 配置
        enable_oauth = bool(project_cfg.get("enable_oauth_token", True))
        oauth_client_id = str(project_cfg.get("oauth_client_id") or "").strip()
        oauth_redirect_uri = str(project_cfg.get("oauth_redirect_uri") or "https://localhost").strip()
        oauth_tenant = str(project_cfg.get("oauth_tenant") or "consumers").strip()
        oauth_scope = str(project_cfg.get("oauth_scope") or "offline_access https://graph.microsoft.com/Mail.Read").strip()

        dbg = RegisterDebug(ctx=ctx, project_id=self.id, email=full_email)
        proxy_info = await ctx.proxy.acquire()
        ctx.log(f"开始 Outlook 注册: {full_email}")
        ctx.log(f"浏览器底座: {browser_backend} | 代理: {proxy_info.server if proxy_info else '直连'}")

        context = None
        page = None
        try:
            async with browser_session(
                proxy_info=proxy_info,
                browser_backend=browser_backend,
            ) as (context, page):
                await dbg.start_trace(context)
                humanizer = Humanizer(page, bot_protection_wait=bot_wait)
                state: dict = {"t0": time.monotonic()}

                steps = [
                    ("step01_open_create", lambda: step01_open_create.run(page, humanizer, state)),
                    (
                        "step02_fill_account",
                        lambda: step02_fill_account.run(
                            page, humanizer,
                            alias=alias, password=password,
                            email_suffix=email_suffix, person=person,
                        ),
                    ),
                    (
                        "step03_fill_profile",
                        lambda: step03_fill_profile.run(
                            page, humanizer,
                            person=person, state=state, bot_protection_wait=bot_wait,
                        ),
                    ),
                    (
                        "step04_solve_captcha",
                        lambda: step04_solve_captcha.run(page, ctx, humanizer, max_retries=max_captcha_retries),
                    ),
                    (
                        "step05_bind_recovery",
                        lambda: step05_bind_recovery.run(page, ctx, humanizer, mail_timeout=mail_timeout),
                    ),
                ]
                if enable_oauth and oauth_client_id:
                    steps.append(
                        (
                            "step06_oauth_token",
                            lambda: step06_oauth_token.run(
                                page, ctx,
                                client_id=oauth_client_id,
                                redirect_uri=oauth_redirect_uri,
                                tenant=oauth_tenant,
                                scope=oauth_scope,
                                account_email=full_email,
                                timeout=180.0,
                            ),
                        ),
                    )

                recovery_email = ""
                oauth_tokens: dict = {}
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
                    if step_id == "step05_bind_recovery":
                        recovery_email = outcome.value or ""
                    elif step_id == "step06_oauth_token" and isinstance(outcome.value, dict):
                        oauth_tokens = outcome.value

                await dbg.success_cleanup(context)
                extra: dict[str, Any] = {
                    "password": password,
                    "recovery_email": recovery_email,
                    "email_suffix": email_suffix,
                    "registered_via": "browser",
                }
                if oauth_tokens:
                    extra.update(
                        {
                            "refresh_token": oauth_tokens.get("refresh_token", ""),
                            "access_token": oauth_tokens.get("access_token", ""),
                            "client_id": oauth_client_id,
                            "tenant": oauth_tenant,
                            "scope": oauth_tokens.get("scope") or oauth_scope,
                            "expires_in": oauth_tokens.get("expires_in"),
                            "oauth_token_type": oauth_tokens.get("token_type", "Bearer"),
                        }
                    )
                    ctx.log(
                        f"OAuth 已写入 extra: refresh_token({len(extra['refresh_token'])}B), "
                        f"client_id={oauth_client_id[:8]}..., tenant={oauth_tenant}"
                    )
                else:
                    extra["oauth_skipped"] = True
                ctx.log(f"Outlook 注册成功: {full_email}")
                return dbg.ok_result(
                    email=full_email,
                    apikey=password,
                    status="ok",
                    extra=extra,
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
        finally:
            if proxy_info:
                await ctx.proxy.release(proxy_info)


PROJECT = OutlookRegisterProject()
