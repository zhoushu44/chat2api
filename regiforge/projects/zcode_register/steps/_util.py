"""私有共享：随机用户名 / 密码、滑块可见性判断（zcode 项目专用）。"""
from __future__ import annotations

import random
import string

from typing import Any


def rand_name() -> str:
    return "z" + "".join(random.choices(string.ascii_lowercase + string.digits, k=10))


def rand_password() -> str:
    return "Zc" + "".join(random.choices(string.ascii_letters + string.digits, k=12)) + "@"


async def captcha_visible(page: Any) -> bool:
    """阿里云滑块弹层是否可见（img 或「点击开始验证」按钮）。"""
    img = page.locator("#aliyunCaptcha-img")
    if await img.count() and await img.is_visible():
        return True
    start = page.locator("text=点击开始验证").first
    return bool(await start.count()) and await start.is_visible()
