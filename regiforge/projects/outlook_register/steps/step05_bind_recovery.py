"""step05：绑定辅助邮箱并回填安全代码（注册收尾）。

对应外部仓库 base_controller.outlook_register 的「验证码通过后，绑定辅助邮箱服务」：
  ctx.email 创建临时邮箱 → 填入 #EmailAddress → 点 #iNext → 等安全代码 →
  填入 #iOttText → 点 #iNext 完成绑定。
"""
from __future__ import annotations

import asyncio
import time
from typing import Any


async def run(
    page: Any,
    ctx: Any,
    humanizer: Any,
    mail_timeout: float = 180,
) -> str:
    if ctx.email is None:
        raise RuntimeError("Outlook 注册需要辅助邮箱 Provider（如 email.tempmail）接收安全代码")

    recovery_email = await asyncio.to_thread(ctx.email.generate_address)
    ctx.log(f"辅助邮箱: {recovery_email}")

    # 验证码通过后微软可能插入「创建通行密钥 (passkey)」推广页
    # （login.microsoft.com/consumers/fido/create），需点「跳过」跳过；
    # 也可能直接停在辅助邮箱页。轮询直至 #EmailAddress 出现。
    email_input = page.locator("#EmailAddress")
    deadline = time.monotonic() + 90
    skipped_passkey = False
    while time.monotonic() < deadline:
        try:
            if await email_input.count() > 0 and await email_input.first.is_visible():
                break
        except Exception:
            pass  # 页面导航瞬间（Execution context destroyed）等下一轮

        if not skipped_passkey:
            try:
                url = page.url or ""
                on_passkey = "fido" in url
                if not on_passkey:
                    on_passkey = await page.get_by_text("通行密钥").count() > 0
                if on_passkey:
                    for label in ["跳过", "暂时跳过", "以后再说", "取消", "Skip for now", "Skip", "Not now"]:
                        btn = page.get_by_role("button", name=label).first
                        if await btn.count() > 0 and await btn.is_visible():
                            ctx.log(f"检测到通行密钥推广页，点击「{label}」跳过")
                            await humanizer.smooth_click(btn)
                            skipped_passkey = True
                            await page.wait_for_timeout(2000)
                            break
            except Exception:
                pass
        await page.wait_for_timeout(1000)
    else:
        raise TimeoutError("90s 内未到达辅助邮箱页（#EmailAddress 未出现，可能停在通行密钥页）(selector_missing)")

    email_input = email_input.first
    await humanizer.smooth_type(email_input, recovery_email)
    await humanizer.wait_ratio(0.03)

    next_btn = page.locator("#iNext").first
    await humanizer.smooth_click(next_btn)

    code = await ctx.email.wait_code(recovery_email, timeout=mail_timeout)
    if not code:
        raise TimeoutError(
            f"辅助邮箱 {recovery_email} 未在 {int(mail_timeout)}s 内收到 Microsoft 安全代码 (email_timeout)"
        )
    ctx.log(f"已收到安全代码 {code}")

    code_input = page.locator("#iOttText")
    await code_input.wait_for(state="visible", timeout=20000)
    await humanizer.smooth_type(code_input, code)
    await humanizer.wait_ratio(0.03)
    await humanizer.smooth_click(next_btn)

    # 校验是否报错（验证码不正确）
    await page.wait_for_timeout(2500)
    try:
        body = await page.locator("body").inner_text(timeout=3000)
    except Exception:
        body = ""
    if "不正确" in body or "验证码错误" in body or "代码不正确" in body:
        raise RuntimeError("辅助邮箱验证码校验失败，微软拒绝该代码 (email_timeout)")

    # 简单确认绑定流程结束（账号已创建 + 辅助邮箱已绑）
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        await page.wait_for_timeout(1000)
        try:
            body = await page.locator("body").inner_text(timeout=2000)
        except Exception:
            body = ""
        try:
            entered_mail = (
                await page.locator('[aria-label="新邮件"]').count() > 0
                or "outlook.live.com/mail" in page.url
            )
        except Exception:
            entered_mail = False
        if entered_mail:
            ctx.log("辅助邮箱绑定完成，已进入邮箱主界面")
            break
        if "不正确" in body or "验证码错误" in body or "代码不正确" in body:
            raise RuntimeError("辅助邮箱验证码校验失败，微软拒绝该代码 (email_timeout)")
    return recovery_email
