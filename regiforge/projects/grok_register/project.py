from __future__ import annotations

import asyncio

from core.base import RegistrationProject, RunContext
from core.models import AccountResult
from core.step_debug import RegisterDebug

from .steps._lite_engine import register_lite


class GrokRegisterProject(RegistrationProject):
    id = "grok_register"
    name = "xAI / Grok"
    description = (
        "注册 xAI/Grok：HTTP 协议注册（curl_cffi + YesCaptcha + TempMail），"
        "复用共用邮箱/代理/Turnstile Provider，产出 SSO"
    )
    required_captcha_types = ["turnstile"]

    async def run_one(self, ctx: RunContext) -> AccountResult:
        project_cfg = (ctx.config.get("projects") or {}).get(self.id) or {}
        mail_timeout = float(project_cfg.get("mail_timeout") or 120)
        turnstile_timeout = float(project_cfg.get("turnstile_timeout") or 180)
        user_agent = str(project_cfg.get("user_agent") or "").strip()

        email = await asyncio.to_thread(ctx.email.generate_address)
        dbg = RegisterDebug(ctx=ctx, project_id=self.id, email=email)
        proxy_info = await ctx.proxy.acquire()

        # 构建代理 URL
        proxy_url = ""
        if proxy_info:
            proxy_url = proxy_info.server

        ctx.log(f"开始 xAI/Grok lite 注册，邮箱: {email}")
        ctx.log(f"代理: {proxy_url or '直连'}")

        async def _wait_code(addr: str, timeout: float):
            return await ctx.email.wait_code(addr, timeout=timeout)

        async def _solve_turnstile(*, sitekey: str, page_url: str, **kwargs):
            return await ctx.captcha.solve(sitekey=sitekey, page_url=page_url, timeout=turnstile_timeout, **kwargs)

        try:
            result = await register_lite(
                proxy=proxy_url or None,
                mail_timeout=mail_timeout,
                turnstile_timeout=turnstile_timeout,
                user_agent=user_agent or None,
                generate_address=lambda: _already_generated(email),
                wait_code=_wait_code,
                solve_turnstile=_solve_turnstile,
                log=ctx.log,
            )

            sso = result.get("sso") or ""
            error = result.get("error") or ""

            if error:
                ctx.log(f"注册失败: {error}")
                return await dbg.fail(
                    None, None,
                    step_id="lite_register",
                    status="fail_lite",
                    error=error,
                    failure_class=_classify_error(error),
                )

            if not sso:
                return await dbg.fail(
                    None, None,
                    step_id="lite_register",
                    status="fail_no_sso",
                    error="注册未返回 SSO",
                    failure_class="exception",
                )

            ctx.log(f"SSO 已取得（长度 {len(sso)}）")
            return dbg.ok_result(
                email=result.get("email") or email,
                apikey=sso,
                status="ok",
                extra={
                    "provider": "grok_web",
                    "authType": "sso",
                    "webTier": "web",
                    "registered_via": "lite",
                },
            )

        except Exception as exc:
            msg = str(exc)
            return await dbg.fail(
                None, None,
                step_id="lite_register",
                status="fail_exception",
                error=msg,
                failure_class=_classify_error(msg),
            )
        finally:
            if proxy_info:
                await ctx.proxy.release(proxy_info)


async def _already_generated(email: str) -> str:
    """generate_address 已在 run_one 中调用，此处直接返回。"""
    return email


def _classify_error(msg: str) -> str:
    """根据错误消息分类 failure_class。"""
    text = (msg or "").lower()
    if "cloudflare" in text or "403" in text or "blocked" in text:
        return "blocked_cf"
    if "turnstile" in text or "captcha" in text:
        return "captcha_fail"
    if "verifyemailvalidationcode" in text or "verification_code" in text:
        return "verification_code_invalid"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "email" in text or "验证码" in text:
        return "email_timeout"
    if "proxy" in text or "connection" in text:
        return "proxy_dead"
    return "exception"


PROJECT = GrokRegisterProject()
