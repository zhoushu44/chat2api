from __future__ import annotations

import asyncio

from core.base import RegistrationProject, RunContext
from core.browser_runner import browser_session, resolve_browser_backend
from core.models import AccountResult
from core.step_debug import RegisterDebug, status_for_class

from .steps import (
    PASSWORD,
    _setup_hcaptcha_route,
    step01_open_signin,
    step02_accept_cookies,
    step03_email_next,
    step06_input_password,
    step07_confirm_password,
    step08_check_agreement,
    step09_solve_captcha,
    step10_inject_token,
    step11_create_account,
    step12_verify_email,
    step13_fetch_apikey,
)
from .steps._hybrid_engine import register_hybrid


class NvidiaBuildProject(RegistrationProject):
    id = "nvidia_build"
    name = "NVIDIA Build"
    description = "批量注册 NVIDIA Build 并获取 AI Playground API Key（支持 browser / http 双模式）"
    required_captcha_types = ["hcaptcha"]

    async def run_one(self, ctx: RunContext) -> AccountResult:
        email = await asyncio.to_thread(ctx.email.generate_address)
        project_cfg = (ctx.config.get("projects") or {}).get(self.id) or {}
        
        # 获取注册模式配置
        register_mode = str(project_cfg.get("register_mode") or "browser").strip().lower()
        if register_mode not in ("browser", "http"):
            register_mode = "browser"
        
        ctx.log(f"开始 NVIDIA 注册，邮箱：{email}")
        ctx.log(f"注册模式：{register_mode}")
        
        if register_mode == "http":
            return await self._run_http(ctx, email=email)
        else:
            return await self._run_browser(ctx, email=email)

    async def _run_http(self, ctx: RunContext, *, email: str) -> AccountResult:
        """HTTP 模式注册（混合：patchright 过 CF + curl_cffi 注册 + patchright 接管 OTP/API Key）。"""
        dbg = RegisterDebug(ctx=ctx, project_id=self.id, email=email)
        ctx.log("HTTP 模式（混合）：patchright 过 CF + curl_cffi 注册 + patchright 接管 OTP/API Key")
        ctx.log(f"证据目录：{dbg.evidence_dir}")

        project_cfg = (ctx.config.get("projects") or {}).get(self.id) or {}
        password = project_cfg.get("password") or PASSWORD
        mail_timeout = float(project_cfg.get("mail_timeout") or 120)
        captcha_timeout = float(project_cfg.get("captcha_timeout") or 180)
        headless = bool(project_cfg.get("headless") or False)

        proxy_info = await ctx.proxy.acquire()
        if proxy_info:
            ctx.log(f"代理：{proxy_info.server} {proxy_info.meta}")
        else:
            ctx.log("代理：直连")

        async def wait_code(addr: str, timeout: float):
            return await ctx.email.wait_code(addr, timeout=timeout)

        async def wait_link(addr: str, timeout: float):
            # "点击邮件链接"验证模式：从邮件提取验证 URL
            if hasattr(ctx.email, "wait_link"):
                return await ctx.email.wait_link(addr, timeout=timeout)
            return None

        async def solve_captcha(*, sitekey: str, page_url: str, **kwargs):
            return await ctx.captcha.solve(sitekey=sitekey, page_url=page_url, timeout=captcha_timeout, **kwargs)

        try:
            result = await register_hybrid(
                email=email,
                password=password,
                proxy_info=proxy_info,
                config=ctx.config,
                project_id=self.id,
                headless=headless,
                solve_captcha_fn=solve_captcha,
                wait_code_fn=wait_code,
                wait_link_fn=wait_link,
                log=ctx.log,
            )

            if not result:
                return await dbg.fail(
                    None, None,
                    step_id="http_register",
                    status="fail_http",
                    error="混合注册未返回结果",
                    failure_class="exception",
                )

            apikey = result.get("apikey") or ""
            error = result.get("error") or ""

            if error and not apikey:
                ctx.log(f"注册失败：{error}")
                return await dbg.fail(
                    None, None,
                    step_id="http_register",
                    status="fail_http",
                    error=error,
                    failure_class=_classify_error(error),
                )

            if not apikey:
                return await dbg.fail(
                    None, None,
                    step_id="http_register",
                    status="fail_no_key",
                    error="HTTP 注册未返回 API Key",
                    failure_class="exception",
                )

            ctx.log(f"API Key 已获取：{apikey[:20]}...")
            return dbg.ok_result(
                email=email,
                apikey=apikey,
                status="ok",
                extra={
                    "mode": "http",
                    "apikey_prefix": (apikey or "")[:6],
                },
            )

        except Exception as exc:
            return await dbg.fail(
                None, None,
                step_id="http_register",
                status="fail_exception",
                error=str(exc),
                failure_class="exception",
            )
        finally:
            if proxy_info:
                await ctx.proxy.release(proxy_info)

    async def _run_browser(self, ctx: RunContext, *, email: str) -> AccountResult:
        """浏览器模式注册（Playwright）。"""
        dbg = RegisterDebug(ctx=ctx, project_id=self.id, email=email)
        ctx.log(f"证据目录：{dbg.evidence_dir}")

        def sync_fetch_safe(target_email: str, timeout: int = 120, skip_codes=None):
            import asyncio

            try:
                loop = asyncio.new_event_loop()
                try:
                    return loop.run_until_complete(
                        ctx.email.wait_code(target_email, timeout=timeout, skip_codes=skip_codes)
                    )
                finally:
                    loop.close()
            except TypeError:
                # 老接口 Provider 无 skip_codes 参数 —— 退回原签名
                loop = asyncio.new_event_loop()
                try:
                    return loop.run_until_complete(ctx.email.wait_code(target_email, timeout=timeout))
                finally:
                    loop.close()
            except Exception as exc:
                ctx.log(f"读验证码异常：{exc}")
                return None

        step12_verify_email.set_code_fetcher(sync_fetch_safe)

        project_cfg = (ctx.config.get("projects") or {}).get(self.id) or {}
        password = project_cfg.get("password") or PASSWORD
        browser_channel = str(project_cfg.get("browser_channel") or "chrome").strip()
        browser_backend = resolve_browser_backend(ctx.config, project_id=self.id)
        user_agent = str(project_cfg.get("user_agent") or "").strip()
        # 让 step12 收码用项目配置的 mail_timeout，而非写死 120s（mailnest 偶发延迟时这116 s 决定成败）
        step12_verify_email.set_mail_timeout(float(project_cfg.get("mail_timeout") or 120))
        import projects.nvidia_build.steps._rpa as rpa_mod
        import projects.nvidia_build.steps._flow as flow_mod

        old_password = rpa_mod.PASSWORD
        rpa_mod.PASSWORD = password
        flow_mod.PASSWORD = password

        proxy_info = await ctx.proxy.acquire()
        if proxy_info:
            ctx.log(f"代理：{proxy_info.server} {proxy_info.meta}")
        else:
            ctx.log("代理：直连")
        ctx.log(f"浏览器底座：{browser_backend}")

        apikey = None
        context = None
        page = None
        try:
            async with browser_session(
                proxy_info=proxy_info,
                browser_channel=browser_channel,
                browser_backend=browser_backend,
                user_agent=user_agent,
                setup_context=_setup_hcaptcha_route,
            ) as (context, page):
                await dbg.start_trace(context)

                steps = [
                    ("step01_open_signin", lambda: step01_open_signin.run(page)),
                    ("step02_accept_cookies", lambda: step02_accept_cookies.run(page)),
                    ("step03_email_next", lambda: step03_email_next.run(page, email)),
                    ("step06_input_password", lambda: step06_input_password.run(page)),
                    ("step07_confirm_password", lambda: step07_confirm_password.run(page)),
                    ("step08_check_agreement", lambda: step08_check_agreement.run(page)),
                ]
                for step_id, step_fn in steps:
                    outcome = await dbg.run_step(page, step_id, step_fn)
                    if outcome.ok:
                        continue
                    if step_id == "step03_email_next":
                        ctx.log("step03 失败，重试 step01+02+03...")
                        recovered = False
                        for _retry in range(2):
                            await dbg.run_step(page, "step01_open_signin", lambda: step01_open_signin.run(page))
                            await dbg.run_step(page, "step02_accept_cookies", lambda: step02_accept_cookies.run(page))
                            retry_out = await dbg.run_step(
                                page, "step03_email_next", lambda: step03_email_next.run(page, email)
                            )
                            if retry_out.ok:
                                ctx.log(f"step03 重试第{_retry + 1}次成功")
                                recovered = True
                                break
                        if recovered:
                            continue
                    return await dbg.fail(
                        page,
                        context,
                        step_id=step_id,
                        status=status_for_class(outcome.failure_class, step_id),
                        error=outcome.error,
                        failure_class=outcome.failure_class,
                    )

                try:
                    sitekey = await step09_solve_captcha.extract_sitekey(page)
                    if not sitekey:
                        return await dbg.fail(
                            page,
                            context,
                            step_id="step09_solve_captcha",
                            status="fail_captcha",
                            error="无法提取 hCaptcha sitekey",
                            failure_class="captcha_fail",
                        )
                    ctx.log(f"sitekey={sitekey}")
                    token = await ctx.captcha.solve(sitekey=sitekey, page_url=page.url)
                    if not token:
                        return await dbg.fail(
                            page,
                            context,
                            step_id="step09_solve_captcha",
                            status="fail_captcha",
                            error="验证码未拿到 token",
                            failure_class="captcha_fail",
                        )
                    ctx.log(f"验证码 token 长度={len(token)}")
                except Exception as e:
                    return await dbg.fail(
                        page,
                        context,
                        step_id="step09_solve_captcha",
                        status="fail_captcha",
                        error=str(e),
                        failure_class="captcha_fail",
                    )

                inject = await dbg.run_step(
                    page, "step10_inject_token", lambda: step10_inject_token.run(page, token), false_is_fail=False
                )
                if not inject.ok:
                    return await dbg.fail(
                        page,
                        context,
                        step_id="step10_inject_token",
                        status=status_for_class(inject.failure_class, "step10_inject_token"),
                        error=inject.error,
                        failure_class=inject.failure_class,
                    )

                create = await dbg.run_step(
                    page, "step11_create_account", lambda: step11_create_account.run(page), false_is_fail=False
                )
                if not create.ok:
                    return await dbg.fail(
                        page,
                        context,
                        step_id="step11_create_account",
                        status=status_for_class(create.failure_class, "step11_create_account"),
                        error=create.error,
                        failure_class=create.failure_class,
                    )

                verify = await dbg.run_step(
                    page, "step12_verify_email", lambda: step12_verify_email.run(page, email)
                )
                if not verify.ok or verify.value is False:
                    return await dbg.fail(
                        page,
                        context,
                        step_id="step12_verify_email",
                        status="fail_email_verification",
                        error=verify.error or "邮箱验证未完成",
                        failure_class=verify.failure_class or "email_timeout",
                    )

                key_out = await dbg.run_step(
                    page,
                    "step13_fetch_apikey",
                    lambda: step13_fetch_apikey.run(page, email),
                    false_is_fail=False,
                )
                if not key_out.ok:
                    return await dbg.fail(
                        page,
                        context,
                        step_id="step13_fetch_apikey",
                        status=status_for_class(key_out.failure_class, "step13_fetch_apikey"),
                        error=key_out.error,
                        failure_class=key_out.failure_class,
                    )
                apikey = key_out.value

                await dbg.success_cleanup(context)
                ctx.log(f"完成 URL={page.url}")
                return dbg.ok_result(
                    apikey=apikey,
                    status="ok" if apikey else "no_key",
                    extra={
                        "mode": "browser",
                        "apikey_prefix": (apikey or "")[:6],
                    },
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
            rpa_mod.PASSWORD = old_password
            if proxy_info:
                await ctx.proxy.release(proxy_info)


def _classify_error(msg: str) -> str:
    """根据错误消息分类 failure_class。"""
    text = (msg or "").lower()
    if "cloudflare" in text or "403" in text or "blocked" in text:
        return "blocked_cf"
    if "hcaptcha" in text or "captcha" in text:
        return "captcha_fail"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "email" in text or "验证码" in text:
        return "email_timeout"
    if "proxy" in text or "connection" in text:
        return "proxy_dead"
    return "exception"


PROJECT = NvidiaBuildProject()
