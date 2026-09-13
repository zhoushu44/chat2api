"""step04：MailNest 轮询收验证邮件，提取 verify 链接并打开，等待「完成注册」表单。"""
from __future__ import annotations

import asyncio
import re
import time

from typing import Any


async def run(page: Any, ctx: Any, email: str, timeout: float = 180) -> str:
    deadline = time.monotonic() + timeout
    link = ""
    while time.monotonic() < deadline:
        mails = await asyncio.to_thread(ctx.email._receive_once, email)
        if mails:
            combined = "\n".join(
                str(m.get(k) or "") for m in mails for k in ("subject", "body", "body_preview", "html", "content")
            )
            match = re.search(r"https://chat\.z\.ai[^\s\"'<>\\]*verify[^\s\"'<>\\]*", combined)
            if not match:
                match = re.search(r"https://[^\s\"'<>\\]+", combined)
            link = match.group(0) if match else ""
            link = link.replace("&amp;", "&")  # HTML 实体转义还原
            ctx.log(f"收到邮件 {len(mails)} 封，提取链接: {link[:120]}")
            if link:
                break
        await page.wait_for_timeout(5000)
    if not link:
        raise TimeoutError(f"未在 {int(timeout)}s 内收到验证邮件链接")

    # 验证链接页是 JS 渲染（Vue SPA），导航慢时 domcontentloaded 可能 60s 都不触发，
    # 改用 commit 只等导航开始，表单由下方 body 轮询兜底
    await page.goto(link, wait_until="commit", timeout=60_000)
    # 轮询等待「完成注册」表单出现
    # 代理抖动时会丢 JS 包导致 Vue 不挂载（body 长时间为空），空 15s 就 reload 一次再等
    deadline = time.monotonic() + 75
    body = ""
    empty_since: float | None = None
    reloaded = 0
    while time.monotonic() < deadline:
        await page.wait_for_timeout(1500)
        try:
            body = await page.locator("body").inner_text(timeout=3000)
        except Exception:
            body = ""
        if "完成注册" in body or "密码" in body:
            ctx.log("验证链接已生效，完成注册表单出现")
            break
        if body.strip():
            empty_since = None
        elif empty_since is None:
            empty_since = time.monotonic()
        elif time.monotonic() - empty_since > 15 and reloaded < 2:
            reloaded += 1
            ctx.log("验证页 body 长时间为空，reload 重试")
            try:
                await page.reload(wait_until="commit", timeout=60_000)
            except Exception:
                pass
            empty_since = None
        ctx.log(f"验证链接页面渲染中，当前 body={body[:80]!r}")
    if "完成注册" not in body and "密码" not in body:
        raise RuntimeError(f"验证链接页面异常：{body[:200]}")
    return link
