"""注册流程可观测性：结构化步骤日志 + 失败证据（截图/HTML/meta/trace）。

吸收 Playwright retain-on-failure / Healer 思路：
- 每步 START/OK/FAIL 可定位
- 失败时浏览器仍存活时落盘证据
- tracing 全程录、仅失败保留 zip
- 失败分类便于 skill 对症修
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar

from .base import RunContext
from .models import AccountResult
from .paths import account_debug_dir

T = TypeVar("T")

# 稳定失败分类（skill / 报表用）
CLASS_SELECTOR = "selector_missing"
CLASS_TIMEOUT = "timeout"
CLASS_PAGE_CLOSED = "page_closed"
CLASS_NAV = "navigation_wrong"
CLASS_CAPTCHA = "captcha_fail"
CLASS_EMAIL = "email_timeout"
CLASS_BLOCKED = "blocked_cf"
CLASS_PROXY = "proxy_dead"
CLASS_UNEXPECTED = "unexpected_ui"
CLASS_FALSE = "step_returned_false"
CLASS_EXCEPTION = "exception"


def debug_config(ctx: RunContext | None = None, config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config if config is not None else (ctx.config if ctx else {})
    raw = (cfg or {}).get("debug") or {}
    return {
        "trace": bool(raw.get("trace", True)),
        "screenshot_on_fail": bool(raw.get("screenshot_on_fail", True)),
        "save_html_on_fail": bool(raw.get("save_html_on_fail", True)),
        "keep_open_on_fail_seconds": max(0, float(raw.get("keep_open_on_fail_seconds") or 0)),
    }


def classify_failure(exc: BaseException | None = None, message: str = "") -> str:
    text = f"{type(exc).__name__ if exc else ''} {exc or ''} {message}".lower()
    if any(k in text for k in ("proxy", "err_proxy", "tunnel", "socks", "econnrefused", "net::err_")):
        return CLASS_PROXY
    if any(k in text for k in ("target closed", "page closed", "browser has been closed", "context closed")):
        return CLASS_PAGE_CLOSED
    if any(
        k in text
        for k in (
            "cloudflare",
            "cf-challenge",
            "attention required",
            "verify you are human",
            "just a moment",
            # Microsoft / Outlook IP 风控：错误信息显式标 "(blocked_cf)"
            # 或页面标题为「帐户创建已被阻止 / 一些异常活动」
            "(blocked_cf)",
            "帐户创建已被阻止",
            "一些异常活动",
            "ip 注册频率",
            "此站点正在维护",
        )
    ):
        return CLASS_BLOCKED
    if any(k in text for k in ("captcha", "hcaptcha", "turnstile", "sitekey")):
        return CLASS_CAPTCHA
    if any(k in text for k in ("email", "otp", "verification code", "wait_code", "inbox", "mail")):
        return CLASS_EMAIL
    if any(k in text for k in ("timeout", "timed out", "exceeded")):
        return CLASS_TIMEOUT
    if any(k in text for k in ("strict mode violation", "resolved to", "not visible", "not found", "no element", "locator", "waiting for selector", "waiting for")):
        return CLASS_SELECTOR
    if any(k in text for k in ("unexpected", "wrong page", "navigat")):
        return CLASS_NAV
    if exc is None and "false" in text:
        return CLASS_FALSE
    if exc is not None:
        return CLASS_EXCEPTION
    return CLASS_UNEXPECTED


def _safe_url(page: Any) -> str:
    try:
        return str(getattr(page, "url", "") or "")
    except Exception:
        return ""


def _safe_title(page: Any) -> str:
    try:
        # title() 可能在已关闭页面上抛错
        result = page.title()
        if asyncio.iscoroutine(result):
            return ""
        return str(result or "")
    except Exception:
        return ""


async def _safe_title_async(page: Any) -> str:
    try:
        return str(await page.title() or "")
    except Exception:
        return ""


@dataclass
class StepOutcome:
    ok: bool
    step_id: str
    value: Any = None
    error: str = ""
    failure_class: str = ""
    elapsed_ms: int = 0
    url: str = ""


@dataclass
class RegisterDebug:
    """单账号注册调试上下文：目录、trace、run_step、失败 AccountResult。"""

    ctx: RunContext
    project_id: str
    email: str = ""
    evidence_dir: Path | None = None
    failed_step: str = ""
    failure_class: str = ""
    last_error: str = ""
    last_url: str = ""
    _tracing: bool = False
    _trace_started: bool = False
    _failed: bool = False
    step_log: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.cfg = debug_config(self.ctx)
        self.evidence_dir = account_debug_dir(self.project_id, self.ctx.task_id, self.ctx.index)

    def _log(self, msg: str) -> None:
        self.ctx.log(msg)

    async def start_trace(self, context: Any) -> None:
        if not self.cfg.get("trace", True):
            return
        try:
            await context.tracing.start(screenshots=True, snapshots=True)
            self._tracing = True
            self._trace_started = True
            self._log(f"trace 已开启（失败时保留）-> {self.evidence_dir}")
        except Exception as exc:
            self._log(f"trace 启动失败（忽略）: {exc}")
            self._tracing = False

    async def stop_trace(self, context: Any, *, keep: bool) -> str:
        if not self._trace_started:
            return ""
        path = ""
        try:
            if keep:
                assert self.evidence_dir is not None
                self.evidence_dir.mkdir(parents=True, exist_ok=True)
                zip_path = self.evidence_dir / "trace.zip"
                await context.tracing.stop(path=str(zip_path))
                path = str(zip_path)
                self._log(f"trace 已保存: {path}")
            else:
                await context.tracing.stop()
        except Exception as exc:
            self._log(f"trace 停止失败（忽略）: {exc}")
        finally:
            self._tracing = False
            self._trace_started = False
        return path

    async def capture(
        self,
        page: Any | None,
        *,
        step_id: str,
        error: str = "",
        failure_class: str = "",
        extra: dict[str, Any] | None = None,
    ) -> str:
        """失败时截图 + HTML + meta.json。返回 evidence_dir 字符串。"""
        assert self.evidence_dir is not None
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        url = _safe_url(page) if page is not None else self.last_url
        self.last_url = url or self.last_url
        title = await _safe_title_async(page) if page is not None else ""
        files: dict[str, str] = {}

        if page is not None and self.cfg.get("screenshot_on_fail", True):
            shot = self.evidence_dir / f"{step_id}.png"
            try:
                await page.screenshot(path=str(shot), full_page=True)
                files["screenshot"] = shot.name
            except Exception as exc:
                try:
                    await page.screenshot(path=str(shot), full_page=False)
                    files["screenshot"] = shot.name
                except Exception as exc2:
                    files["screenshot_error"] = f"{exc}; {exc2}"

        if page is not None and self.cfg.get("save_html_on_fail", True):
            html_path = self.evidence_dir / f"{step_id}.html"
            try:
                content = await page.content()
                html_path.write_text(content or "", encoding="utf-8", errors="replace")
                files["html"] = html_path.name
            except Exception as exc:
                files["html_error"] = str(exc)

        meta = {
            "project_id": self.project_id,
            "task_id": self.ctx.task_id,
            "index": self.ctx.index,
            "email": self.email,
            "step_id": step_id,
            "failure_class": failure_class or self.failure_class,
            "error": error or self.last_error,
            "url": url,
            "title": title,
            "ts": time.time(),
            "files": files,
            "steps": self.step_log[-30:],
            "extra": extra or {},
        }
        meta_path = self.evidence_dir / "meta.json"
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        files["meta"] = meta_path.name
        self._log(
            f"失败证据 step={step_id} class={meta['failure_class']} "
            f"url={url[:120]} dir={self.evidence_dir}"
        )
        return str(self.evidence_dir)

    async def run_step(
        self,
        page: Any,
        step_id: str,
        fn: Callable[..., Awaitable[T]],
        *args: Any,
        false_is_fail: bool = True,
        **kwargs: Any,
    ) -> StepOutcome:
        """执行一步：结构化日志；失败不关浏览器，由调用方 capture。"""
        start = time.perf_counter()
        url0 = _safe_url(page)
        self._log(f"{step_id} START url={url0[:160]}")
        try:
            value = await fn(*args, **kwargs)
            elapsed = int((time.perf_counter() - start) * 1000)
            url1 = _safe_url(page)
            self.last_url = url1 or self.last_url
            if false_is_fail and value is False:
                msg = f"{step_id} 返回 False"
                fc = CLASS_FALSE
                self._log(f"{step_id} FAIL class={fc} {elapsed}ms url={url1[:160]}")
                self.step_log.append(
                    {"step_id": step_id, "ok": False, "elapsed_ms": elapsed, "url": url1, "error": msg, "class": fc}
                )
                self.failed_step = step_id
                self.failure_class = fc
                self.last_error = msg
                self._failed = True
                return StepOutcome(ok=False, step_id=step_id, value=value, error=msg, failure_class=fc, elapsed_ms=elapsed, url=url1)
            self._log(f"{step_id} OK {elapsed}ms url={url1[:160]}")
            self.step_log.append({"step_id": step_id, "ok": True, "elapsed_ms": elapsed, "url": url1})
            # 成功则清掉失败标记（含 step 重试成功）
            self.failed_step = ""
            self.failure_class = ""
            self.last_error = ""
            self._failed = False
            return StepOutcome(ok=True, step_id=step_id, value=value, elapsed_ms=elapsed, url=url1)
        except Exception as exc:
            elapsed = int((time.perf_counter() - start) * 1000)
            url1 = _safe_url(page)
            self.last_url = url1 or self.last_url
            err = f"{type(exc).__name__}: {exc}"
            fc = classify_failure(exc, err)
            self._log(f"{step_id} FAIL class={fc} {elapsed}ms {err} url={url1[:160]}")
            self.step_log.append(
                {
                    "step_id": step_id,
                    "ok": False,
                    "elapsed_ms": elapsed,
                    "url": url1,
                    "error": err,
                    "class": fc,
                    "traceback": traceback.format_exc()[-2000:],
                }
            )
            self.failed_step = step_id
            self.failure_class = fc
            self.last_error = err
            self._failed = True
            return StepOutcome(ok=False, step_id=step_id, error=err, failure_class=fc, elapsed_ms=elapsed, url=url1)

    async def fail(
        self,
        page: Any | None,
        context: Any | None,
        *,
        step_id: str,
        status: str,
        error: str = "",
        failure_class: str = "",
        email: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> AccountResult:
        self._failed = True
        self.failed_step = step_id or self.failed_step
        self.last_error = error or self.last_error
        self.failure_class = failure_class or self.failure_class or classify_failure(message=self.last_error)
        evidence = ""
        if page is not None or self.evidence_dir:
            evidence = await self.capture(
                page,
                step_id=self.failed_step or step_id or "unknown",
                error=self.last_error,
                failure_class=self.failure_class,
                extra=extra,
            )
        if context is not None:
            await self.stop_trace(context, keep=True)
        await self.maybe_keep_open()
        return AccountResult(
            email=email if email is not None else self.email,
            apikey=None,
            status=status,
            failed_step=self.failed_step,
            failure_class=self.failure_class,
            error=self.last_error,
            evidence_dir=evidence,
            last_url=self.last_url,
        )

    async def success_cleanup(self, context: Any | None) -> None:
        if context is not None:
            await self.stop_trace(context, keep=False)

    async def maybe_keep_open(self) -> None:
        seconds = float(self.cfg.get("keep_open_on_fail_seconds") or 0)
        if seconds <= 0 or not self._failed:
            return
        self._log(f"debug.keep_open_on_fail_seconds={seconds}，浏览器暂留（便于目视）")
        await asyncio.sleep(seconds)

    def ok_result(self, *, email: str | None = None, apikey: str | None, status: str = "ok", extra: dict[str, Any] | None = None) -> AccountResult:
        return AccountResult(
            email=email if email is not None else self.email,
            apikey=apikey,
            status=status if apikey else (status if status != "ok" else "no_key"),
            last_url=self.last_url,
            evidence_dir=str(self.evidence_dir or ""),
            extra=extra or {},
        )


def status_for_class(failure_class: str, step_id: str) -> str:
    """把 failure_class 映射成相对稳定的 status 字符串。"""
    mapping = {
        CLASS_CAPTCHA: "fail_captcha",
        CLASS_EMAIL: "fail_email_verification",
        CLASS_BLOCKED: "fail_blocked_cf",
        CLASS_PROXY: "fail_proxy",
        CLASS_PAGE_CLOSED: "fail_page_closed",
        CLASS_SELECTOR: f"fail_{step_id or 'step'}_selector",
        CLASS_TIMEOUT: f"fail_{step_id or 'step'}_timeout",
        CLASS_FALSE: f"fail_{step_id or 'step'}",
        CLASS_NAV: f"fail_{step_id or 'step'}_nav",
        CLASS_UNEXPECTED: f"fail_{step_id or 'step'}",
        CLASS_EXCEPTION: f"fail_{step_id or 'step'}_exception",
    }
    if failure_class in mapping:
        return mapping[failure_class]
    # 兼容旧 fail_stepN：从 step03_xxx 抽编号
    m = re.match(r"step(\d+)", step_id or "")
    if m:
        return f"fail_step{int(m.group(1))}"
    return f"fail_{step_id or 'unknown'}"
