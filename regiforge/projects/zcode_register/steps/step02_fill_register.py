"""step02：填写注册表单（随机用户名 + 邮箱 + 密码），返回 name/password。"""
from __future__ import annotations

from typing import Any

from ._util import rand_name, rand_password


async def run(page: Any, email: str) -> dict:
    name = rand_name()
    password = rand_password()
    await page.get_by_placeholder("输入您的名称").first.fill(name)
    await page.locator("input[name=email]").fill(email)
    await page.locator("input[name=new-password]").fill(password)
    return {"name": name, "password": password}
