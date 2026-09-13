"""step02：填写邮箱别名 + 密码，按需选择 @hotmail.com 域名与出生日期。

对应外部仓库 base_controller.outlook_register：
  邮箱别名 → 密码 → （可选生日表单）→ 提交进入资料页。
"""
from __future__ import annotations

from typing import Any

PRIMARY_BTN = '[data-testid="primaryButton"]'


async def run(
    page: Any,
    humanizer: Any,
    *,
    alias: str,
    password: str,
    email_suffix: str = "@outlook.com",
    person: dict,
) -> bool:
    # 选择 @hotmail.com 域名（默认 @outlook.com 无需操作）
    if email_suffix == "@hotmail.com":
        await humanizer.wait_ratio(0.06)
        domain_btn = page.get_by_text("@outlook.com").first
        await humanizer.smooth_click(domain_btn)
        option_btn = page.locator('[role="option"]:text-is("@hotmail.com")').first
        await humanizer.smooth_click(option_btn)

    # 邮箱别名（页面脚本慢加载时先等输入框可见）
    email_input = page.locator('[aria-label="新建电子邮件"]')
    await email_input.wait_for(state="visible", timeout=60000)
    await humanizer.smooth_type(email_input, alias)

    primary_btn = page.locator(PRIMARY_BTN).first
    await humanizer.smooth_click(primary_btn)
    await humanizer.wait_ratio(0.04)

    # 密码
    pwd_input = page.locator('[type="password"]').first
    await pwd_input.wait_for(state="visible", timeout=30000)
    await humanizer.smooth_type(pwd_input, password)
    await humanizer.wait_ratio(0.03)
    await humanizer.smooth_click(primary_btn)
    await humanizer.wait_ratio(0.03)

    if await page.get_by_text("请重试。如果仍然不起作用，请稍后再试。").count() > 0:
        raise RuntimeError("当前 IP 注册频率过快，被微软拒绝（blocked_cf）")

    # 部分地区/随机出现出生日期表单
    year_input = page.locator('[name="BirthYear"]')
    if await year_input.count() > 0:
        await humanizer.smooth_click(year_input)
        await year_input.fill(person["year"])

        month_btn = page.locator('[name="BirthMonth"]').first
        await humanizer.smooth_click(month_btn)
        await humanizer.wait_ratio(0.03)
        m_opt = page.locator(f'[role="option"]:text-is("{person["month"]}月")').first
        await humanizer.smooth_click(m_opt)

        await humanizer.wait_ratio(0.03)
        day_btn = page.locator('[name="BirthDay"]').first
        await humanizer.smooth_click(day_btn)
        await humanizer.wait_ratio(0.03)
        d_opt = page.locator(f'[role="option"]:text-is("{person["day"]}日")').first
        try:
            await d_opt.scroll_into_view_if_needed()
        except Exception:
            pass
        await humanizer.smooth_click(d_opt)

    # 提交（无生日表单时这里是 邮箱+密码 的下一步）
    await humanizer.smooth_click(primary_btn)
    return True
