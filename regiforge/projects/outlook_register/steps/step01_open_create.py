"""step01：打开 Outlook 创建账号页，接受「同意并继续」隐私同意。

对应外部仓库 base_controller.outlook_register 的入口部分：
page.goto(create_account URL) → 点击同意并继续（cookie 已接受时可能不出现）。
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any

CREATE_ACCOUNT_URL = "https://outlook.live.com/mail/0/?prompt=create_account"


async def run(page: Any, humanizer: Any, state: dict) -> bool:
    state["t0"] = time.monotonic()
    try:
        # 代理/CDN 慢时 domcontentloaded 可能长时间不触发（defer 脚本多）。
        # 用 commit（响应头到达即算导航完成），页面继续后台加载，后续以 UI 等待为准。
        await page.goto(CREATE_ACCOUNT_URL, timeout=90000, wait_until="commit")
    except Exception:
        pass  # goto 超时不算致命，页面仍在加载，交给下方 UI 等待
    state["t0"] = time.monotonic()

    # 代理下重定向链很慢：
    # outlook.live.com/mail → login.microsoftonline.com/consumers/oauth2 → signup.live.com/signup
    # 实测需 25~60s 才到达注册页并渲染出按钮，因此先等 URL 稳定到注册域。
    try:
        await page.wait_for_url(
            re.compile(r"signup\.live\.com|login\.microsoftonline\.com"),
            timeout=120000,
        )
    except Exception:
        pass  # 不强制，交给下方按钮轮询兜底

    consent_btn = page.get_by_text("同意并继续").first
    email_input = page.locator('[aria-label="新建电子邮件"]').first

    # 长轮询：同意并继续（隐私同意页）/ 新建电子邮件（表单页）任一出现即继续
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            if await consent_btn.is_visible(timeout=3000):
                await humanizer.wait_ratio(0.06)
                await humanizer.smooth_click(consent_btn)
                state["t0"] = time.monotonic()
                return True
        except Exception:
            pass  # 元素未出现或页面仍在跳转，继续轮询
        try:
            if await email_input.is_visible(timeout=3000):
                state["t0"] = time.monotonic()
                return True
        except Exception:
            pass
        await asyncio.sleep(3)

    raise TimeoutError(
        "打开注册页后未等到「同意并继续 / 新建电子邮件」输入框"
        "（页面加载过慢或当前 IP 被微软拒绝）"
    )
