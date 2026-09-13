from __future__ import annotations

import asyncio
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from core.base import RegistrationProject, RunContext
from core.browser_runner import browser_session, resolve_browser_backend
from core.models import AccountResult, ProxyInfo
from core.step_debug import RegisterDebug, classify_failure, status_for_class

from .steps import (
    step01_open_login,
    step02_submit_email,
    step03_verify_email,
    step04_complete_profile,
    step05_extract_session,
    step06_setup_2fa,
)
from .steps._http_engine import register_http, _decode_jwt_plan_type


def _refresh_token_log_path() -> Path:
    """refresh_token 持久化：data/keys/chatgpt_register/refresh_tokens.jsonl。

    access_token 会被 OpenAI 快速 revoke（尤其批量注册），chatgpt2api 号池
    持有 refresh_token 才能自动换新 + keepalive 保活（否则账号"还没生成就死"）。
    """
    from core.paths import KEYS_DIR

    folder = KEYS_DIR / "chatgpt_register"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "refresh_tokens.jsonl"


def _save_refresh_token(email: str, refresh_token: str) -> None:
    """追加保存 email|refresh_token（O_APPEND 原子写，成功才落盘）。"""
    if not email or not refresh_token:
        return
    try:
        line = f"{email}|{refresh_token}\n".encode("utf-8")
        fd = os.open(str(_refresh_token_log_path()), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
    except Exception:
        pass


def _display_proxy(proxy_info) -> str:
    if not proxy_info:
        return "直连（未填写 SOCKS5；如连接被关闭，请填写 socks5:// 地址）"
    parsed = urlsplit(proxy_info.server)
    host = parsed.hostname or "?"
    port = f":{parsed.port}" if parsed.port else ""
    return urlunsplit((parsed.scheme, f"{host}{port}", parsed.path, "", ""))


class ChatGPTRegisterProject(RegistrationProject):
    id = "chatgpt_register"
    name = "ChatGPT / OpenAI"
    description = (
        "MailNest 临时邮箱注册 ChatGPT：支持 browser（有头页面）与 http（Sentinel+API）双模式，"
        "产出 Session Token"
    )
    # browser 模式需要 turnstile；http 模式不强制（UI 仍可展示）
    required_captcha_types: list[str] = ["turnstile"]

    async def run_one(self, ctx: RunContext) -> AccountResult:
        email = await asyncio.to_thread(ctx.email.generate_address)
        project_cfg = (ctx.config.get("projects") or {}).get(self.id) or {}
        mail_timeout = float(project_cfg.get("mail_timeout") or 180)
        profile_timeout = float(project_cfg.get("profile_timeout") or 90)
        session_timeout = float(project_cfg.get("session_timeout") or 120)
        user_agent = str(project_cfg.get("user_agent") or "").strip()
        browser_channel = str(project_cfg.get("browser_channel") or "chrome").strip()
        browser_backend = resolve_browser_backend(ctx.config, project_id=self.id)
        register_mode = str(project_cfg.get("register_mode") or "browser").strip().lower()
        if register_mode not in ("browser", "http"):
            register_mode = "browser"
        fetch_refresh = bool(project_cfg.get("http_fetch_refresh_token", True))
        enable_2fa = bool(project_cfg.get("enable_2fa", False))
        _2fa_timeout = float(project_cfg.get("2fa_timeout") or 120)
        # 注册收口（强制，不读配置开关）：HTTP 模式必然 设密码 + 绑 TOTP 2FA + 立即验活，
        # 三项任一失败即注册失败（详见 docs/需求-注册存活率对齐.md 需求 1）
        sentinel_refresh = bool(project_cfg.get("http_sentinel_refresh", True))

        proxy_info = await ctx.proxy.acquire()
        ctx.acquired_proxy = proxy_info
        ctx.log(f"开始 ChatGPT 注册，邮箱：{email}")
        ctx.log(f"注册模式：{register_mode}")
        ctx.log(f"浏览器底座：{browser_backend}")
        ctx.log(f"网络：{_display_proxy(proxy_info)}")

        # 整段重试时换新出口（代理池如 WARP 每次 acquire 换新 sid/实例，
        # 避免坏实例让多次重试全部失败）；同时让 finally 释放最新出口
        async def _reacquire_proxy(failure_type: str | None = None):
            previous = ctx.acquired_proxy
            if previous:
                await ctx.proxy.release(previous, failure_type=failure_type)
                ctx.acquired_proxy = None
            info = await ctx.proxy.acquire()
            if info is not None:
                ctx.acquired_proxy = info
            return info

        try:
            if register_mode == "http":
                # curl_cffi 不支持 SOCKS5 认证（error 97），
                # forwarder（http://127.0.0.1:xxxx）已处理认证，curl 和 Sentinel 共用
                return await self._run_http(
                    ctx,
                    email=email,
                    proxy_info=proxy_info,
                    sentinel_proxy_info=proxy_info,
                    user_agent=user_agent,
                    browser_backend=browser_backend,
                    mail_timeout=mail_timeout,
                    fetch_refresh=fetch_refresh,
                    sentinel_refresh=sentinel_refresh,
                    reacquire_proxy=_reacquire_proxy,
                )
            return await self._run_browser(
                ctx,
                email=email,
                proxy_info=proxy_info,
                user_agent=user_agent,
                browser_channel=browser_channel,
                browser_backend=browser_backend,
                mail_timeout=mail_timeout,
                profile_timeout=profile_timeout,
                session_timeout=session_timeout,
                enable_2fa=enable_2fa,
                _2fa_timeout=_2fa_timeout,
            )
        finally:
            latest = ctx.acquired_proxy
            if latest:
                ft = ctx.last_failure_class
                await ctx.proxy.release(latest, failure_type=ft)

    async def _run_http(
        self,
        ctx: RunContext,
        *,
        email: str,
        proxy_info,
        sentinel_proxy_info,
        user_agent: str,
        browser_backend: str,
        mail_timeout: float,
        fetch_refresh: bool,
        sentinel_refresh: bool = True,
        reacquire_proxy=None,
    ) -> AccountResult:
        dbg = RegisterDebug(ctx=ctx, project_id=self.id, email=email)
        ctx.log("HTTP 模式：Sentinel + curl_cffi Auth API（oumiFree 兼容）")
        ctx.log("邮箱仍走 ctx.email（mailnest），不复制 IMAP/Graph 实现")
        ctx.log(f"证据目录：{dbg.evidence_dir}")

        async def wait_code(addr: str):
            return await ctx.email.wait_code(addr, timeout=mail_timeout)

        try:
            result = await register_http(
                email=email,
                wait_code=wait_code,
                proxy_info=proxy_info,
                sentinel_proxy_info=sentinel_proxy_info,
                user_agent=user_agent,
                browser_backend=browser_backend,
                mail_timeout=mail_timeout,
                fetch_refresh_token=fetch_refresh,
                sentinel_refresh=sentinel_refresh,
                reacquire_proxy=reacquire_proxy,
                log=ctx.log,
            )
            token = result.get("access_token") or ""
            if not token:
                return await dbg.fail(
                    None,
                    None,
                    step_id="http_register",
                    status="fail_http_no_token",
                    error="HTTP 注册未返回 access_token",
                    failure_class="exception",
                )
            # 注册收口：密码 / TOTP 2FA / 验活 三项必须齐活，否则视为失败不产出
            if not result.get("password"):
                return await dbg.fail(
                    None,
                    None,
                    step_id="http_register",
                    status="fail_http_no_password",
                    error="设密码未成功：无法保证账号可脱离邮箱恢复（注册收口要求）",
                    failure_class="exception",
                )
            if not (result.get("mfa_enabled") and result.get("totp_secret")):
                return await dbg.fail(
                    None,
                    None,
                    step_id="http_register",
                    status="fail_http_no_2fa",
                    error="TOTP 2FA 未绑定：无法保证账号可脱离邮箱恢复（注册收口要求）",
                    failure_class="exception",
                )
            ctx.log("Session Token 已提取，HTTP 注册完成")
            rt = result.get("refresh_token") or ""
            if rt:
                _save_refresh_token(result.get("email") or email, rt)
                ctx.log("✅ refresh_token 已保存（导入号池后开启自动保活，防还没生成就死）")
            ctx.log("✅ 注册收口完成：密码 + TOTP 2FA + 验活 全通过")
            return dbg.ok_result(
                email=result.get("email") or email,
                apikey=token,
                status="ok",
                extra={
                    "mode": "http",
                    "name": result.get("name") or "",
                    "has_refresh_token": bool(result.get("refresh_token")),
                    "has_password": True,
                    "password": result.get("password") or "",
                    "totp_secret": result.get("totp_secret") or "",
                    "mfa_enabled": True,
                    "alive_verified": True,
                    # 对齐 chatgpt2api 账号字段：type/source_type（导入后由其自动刷新 type/quota/status）
                    "type": "free",
                    "source_type": "web",
                    # 订阅类型：从 access_token JWT 的 chatgpt_plan_type 解码（free/plus/pro/team）
                    "plan_type": result.get("plan_type") or "",
                    # 出口观测：国家/时区/指纹（统计哪个出口好；见 _http_engine._append_egress）
                    "egress_country": result.get("egress_country") or "",
                    "egress_tz": result.get("egress_tz") or "",
                    "egress_fingerprint": result.get("egress_fingerprint") or "",
                },
            )
        except Exception as exc:
            fc = classify_failure(exc)
            if fc == "proxy_dead":
                ctx.last_failure_class = fc
            return await dbg.fail(
                None,
                None,
                step_id="http_register",
                status="fail_http_exception",
                error=str(exc),
                failure_class=fc,
            )

    async def _run_browser(
        self,
        ctx: RunContext,
        *,
        email: str,
        proxy_info,
        user_agent: str,
        browser_channel: str,
        browser_backend: str,
        mail_timeout: float,
        profile_timeout: float,
        session_timeout: float,
        enable_2fa: bool = False,
        _2fa_timeout: float = 120,
    ) -> AccountResult:
        dbg = RegisterDebug(ctx=ctx, project_id=self.id, email=email)
        ctx.log("如出现 Cloudflare「验证您是真人」，请在弹出的有头浏览器中手动勾选")
        ctx.log(f"正在启动有头 Chrome 浏览器（底座={browser_backend}）...")
        ctx.log(f"证据目录：{dbg.evidence_dir}")
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
                ctx.log(f"浏览器已启动（单窗口有头模式，底座={browser_backend}）")

                steps = [
                    ("step01_open_login", lambda: step01_open_login.run(page, email)),
                    ("step02_submit_email", lambda: step02_submit_email.run(page, email, ctx=ctx)),
                    (
                        "step03_verify_email",
                        lambda: step03_verify_email.run(page, ctx, email, timeout=mail_timeout),
                    ),
                    (
                        "step04_complete_profile",
                        lambda: step04_complete_profile.run(page, ctx, timeout=profile_timeout),
                    ),
                    (
                        "step05_extract_session",
                        lambda: step05_extract_session.run(page, ctx, timeout=session_timeout),
                    ),
                ]
                
                # 如启用 2FA，添加 2FA 设置步骤
                if enable_2fa:
                    steps.append(
                        ("step06_setup_2fa", lambda: step06_setup_2fa.run(page, ctx, timeout=_2fa_timeout, enable_2fa=True)),
                    )
                
                token = None
                profile = None
                _2fa_result = None
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
                    if step_id == "step03_verify_email":
                        code = outcome.value
                        if code:
                            ctx.log(f"验证码已提交：{str(code)[:2]}****")
                        else:
                            ctx.log("验证码已跳过")
                    elif step_id == "step04_complete_profile":
                        profile = outcome.value or {}
                        ctx.log(f"资料阶段：name={profile.get('name')} age={profile.get('age')}")
                    elif step_id == "step05_extract_session":
                        token = outcome.value
                    elif step_id == "step06_setup_2fa":
                        _2fa_result = outcome.value or {}
                        if _2fa_result.get("enabled"):
                            ctx.log(f"2FA 已启用，TOTP: {_2fa_result.get('totp_secret', 'N/A')[:4]}****")
                        else:
                            ctx.log("2FA 设置未完成")

                await dbg.success_cleanup(context)
                ctx.log("Session Token 已提取，注册完成")
                
                # 构建 extra 信息
                extra = {
                    "mode": "browser",
                    "name": (profile or {}).get("name") or "",
                    # 对齐 chatgpt2api 账号字段：type/source_type（导入后由其自动刷新 type/quota/status）
                    "type": "free",
                    "source_type": "web",
                    # 订阅类型：从 access_token JWT 的 chatgpt_plan_type 解码（free/plus/pro/team）
                    "plan_type": _decode_jwt_plan_type(token) if token else "",
                }
                
                # 如启用 2FA，添加到 extra
                if enable_2fa and _2fa_result:
                    if _2fa_result.get("enabled"):
                        extra["2fa_enabled"] = True
                        extra["totp_secret"] = _2fa_result.get("totp_secret") or ""
                        extra["backup_codes"] = _2fa_result.get("backup_codes") or []
                        ctx.log("✅ 2FA 已配置并保存")
                    else:
                        extra["2fa_enabled"] = False
                        ctx.log("⚠️ 2FA 未成功启用")
                
                return dbg.ok_result(
                    apikey=token,
                    status="ok" if token else "no_key",
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


PROJECT = ChatGPTRegisterProject()
