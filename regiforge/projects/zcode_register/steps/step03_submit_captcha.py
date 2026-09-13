"""step03：点「创建账号」触发滑块 → slider.aliyun 解决 → 再次提交，直到跳转验证邮箱页。"""
from __future__ import annotations

from typing import Any

CREATE_XPATH = 'xpath=//*[@id="app"]/div[1]/div[3]/div/div/div[1]/form/div[3]/button[1]'


async def _click_create(page: Any) -> None:
    create_btn = page.locator(CREATE_XPATH)
    fallback = page.get_by_role("button", name="创建账号").first
    try:
        await create_btn.first.click(timeout=5000)
    except Exception:
        try:
            await fallback.click(timeout=5000)
        except Exception:
            await page.evaluate(
                """() => {
                    const t = [...document.querySelectorAll('button')].find(b =>
                        (b.textContent || '').trim() === '创建账号' && !!(b.offsetWidth || b.offsetHeight));
                    if (t) t.click();
                }"""
            )


async def run(page: Any, ctx: Any, timeout: float = 90) -> bool:
    from ._util import captcha_visible

    for submit_attempt in range(5):
        await _click_create(page)
        ctx.log(f"已点创建账号（第 {submit_attempt + 1} 次）")
        # 轮询：已跳转验证邮箱页 / 出现滑块 / 其他
        result = "none"
        creating = False
        for _ in range(40):  # 20s
            await page.wait_for_timeout(500)
            if "/auth/verify" in page.url:
                result = "submitted"
                break
            if await captcha_visible(page):
                result = "captcha"
                break
            try:
                body_txt = (await page.locator("body").inner_text(timeout=1500))[:200].replace("\n", " ")
            except Exception:
                body_txt = ""
            if "正在创建账户" in body_txt or "验证通过" in body_txt:
                creating = True  # 创建请求处理中，继续等，不能当失败
        if result == "submitted":
            ctx.log("已跳转验证邮箱页")
            return True
        if result == "captcha":
            ctx.log("出现阿里云滑块，调用 slider.aliyun 解决")
            token = await ctx.captcha.solve(page=page, sitekey="", page_url=page.url, timeout=timeout)
            if not token:
                raise RuntimeError("阿里云滑块验证未通过")
            ctx.log("滑块已通过，继续提交")
            continue
        # 无滑块无跳转：诊断页面
        text = (await page.locator("body").inner_text(timeout=3000))[:200].replace("\n", " ")
        if creating or "正在创建账户" in text or "验证通过" in text:
            # 创建请求仍在服务端处理，再等 20s 看是否跳转验证邮箱页
            ctx.log(f"创建请求处理中，继续等待跳转: {text[:80]}")
            for _ in range(40):  # 20s
                await page.wait_for_timeout(500)
                if "/auth/verify" in page.url:
                    ctx.log("创建完成，已跳转验证邮箱页")
                    return True
            text = (await page.locator("body").inner_text(timeout=3000))[:200].replace("\n", " ")
            if "验证您的邮箱" in text or "验证链接" in text:
                return True
            ctx.log(f"创建等待后仍未跳转，页面文本: {text[:120]}")
            if "正在创建账户" in text or "验证通过" in text:
                continue  # 仍在创建中，再点击一次提交
        ctx.log(f"无滑块无跳转，页面文本: {text[:150]}")
        if "验证您的邮箱" in text or "验证链接" in text:
            return True
        if "已经拥有账号" in text or "登录" in text or "跳过" in text:
            raise RuntimeError(f"创建账号提交异常：{text[:120]}")
    raise RuntimeError("创建账号提交未完成（多次无跳转）")
