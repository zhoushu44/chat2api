"""Microsoft FunCaptcha 浏览器内按压挑战（browser_press）。

迁移自外部仓库 `OutlookRegister/controllers/patchright_controller.py`
的 handle_captcha 逻辑，按 RegiForge 异步 Playwright + CaptchaProvider 接口改写。

适用场景：注册 outlook.com / hotmail.com 时出现的
`iframe#enforcementFrame` → `iframe[title="验证质询"]` 按压验证码
（aria-label="可访问性挑战" / "再次按下"）。

用法（由项目步骤调用，页面已停在验证码处）：
    ok = await ctx.captcha.solve(
        sitekey="", page_url=page.url,
        page=page, humanizer=humanizer,
        max_retries=3,
    )
"""
from __future__ import annotations

import random
import time
from typing import Any

from core.base import CaptchaProvider


class BrowserPressFuncaptchaProvider(CaptchaProvider):
    """在浏览器页面内完成 Microsoft 按压验证码（不产出 token）。"""

    type = "funcaptcha"
    id = "browser_press"
    name = "浏览器内按压（Microsoft FunCaptcha）"

    async def solve(self, *, sitekey: str, page_url: str, **kwargs: Any) -> str | None:
        page = kwargs.get("page")
        if page is None:
            raise ValueError("funcaptcha.browser_press 需要传入 Playwright page（kwargs['page']）")
        humanizer = kwargs.get("humanizer")
        max_retries = max(0, int(kwargs.get("max_retries") or 3))

        # 挑战可能已自动通过（无 iframe 或已到辅助邮箱页）
        if await _passed(page):
            return "browser-complete"

        # 按压按钮：旧版 aria-label="再次按下"；新版 "按住" / "按住 人工挑战"（进度环长按）
        press_selector = (
            '[aria-label="再次按下"], [aria-label*="按住"], [aria-label*="人工挑战"]'
        )

        # Arkose 按钮渲染可能明显晚于 iframe；实测正常慢样本约 29 秒。
        # 40 秒仍未派发按钮时，直接结束账号而不是继续空跑。
        ready = await _wait_challenge_ready(page, press_selector, timeout_ms=40000)
        if not ready:
            raise RuntimeError("FunCaptcha 按压按钮等待 40 秒仍未派发 (captcha)")

        a11y_used = False  # 「可访问性挑战」点击会重置挑战，整个 solve 只允许点一次
        keep_going_rounds = 0
        for _attempt in range(max_retries + 1):
            if await _passed(page):
                return "browser-complete"
            if await _rate_limited(page):
                return None
            await page.wait_for_timeout(random.randint(250, 450))

            # 1) 直接找按压按钮（新版渲染在 about:blank 子帧；旧版在嵌套 iframe）
            found = await _find_press_button(page, press_selector)

            # 2) 没有按压按钮时，点一次「可访问性挑战」切换到按压形态
            if found is None and not a11y_used:
                a11y = await _find_press_button(page, '[aria-label="可访问性挑战"]')
                if a11y is not None:
                    await _click(page, humanizer, a11y[0])
                    a11y_used = True
                    await page.wait_for_timeout(random.randint(800, 1500))
                    found = await _find_press_button(page, press_selector)

            if found is None:
                # 按钮仍在渲染：稍等重试（或已通过/风控，下轮循环头部判定）
                await page.wait_for_timeout(2500)
                continue

            # 3) 长按按压按钮：按住直到「松开」提示 / 按钮消失 / 通过 / 超时
            await _hold_press(page, humanizer, found[0], found[1])

            # 4) 等按压结果稳定（挑战重渲染可能要 ~9s：按钮回归=进入下一轮）
            for _ in range(14):  # ~12s
                await page.wait_for_timeout(850)
                if await _passed(page):
                    return "browser-complete"
                if await _rate_limited(page):
                    return None
                if await _keep_going(page):
                    keep_going_rounds += 1
                    if keep_going_rounds >= 2:
                        raise RuntimeError("FunCaptcha 连续两轮 Keep going，当前代理出口风险过高 (captcha)")
                    break
                if await _find_press_button(page, press_selector) is not None:
                    keep_going_rounds = 0
                    break  # 出现下一轮按压按钮
            # 未 break 也继续下一轮 attempt（最终由 _passed / 重试耗尽判定）
        return None


async def _hold_press(page: Any, humanizer: Any, locator: Any, frame: Any) -> dict[str, Any]:
    """按住按压按钮直到挑战状态变化。

    新版 HUMAN「按住」是进度环式长按：需持续按住直到出现「松开」提示或
    进度完成（按钮消失）；过早松开会触发「再次按下」重来。
    """
    try:
        box = await locator.bounding_box()
    except Exception:
        box = None
    if not box:
        # 拿不到坐标则退化为普通点击（聊胜于无）
        clicked = await _click(page, humanizer, locator)
        return {"box": None, "fallback_click": clicked, "reason": "no_box"}

    x = box["x"] + box["width"] / 2 + random.uniform(-2, 2)
    y = box["y"] + box["height"] / 2 + random.uniform(-2, 2)
    started = time.monotonic()
    reason = "deadline"
    error = ""
    try:
        if humanizer is not None and hasattr(humanizer, "smooth_move_to"):
            await humanizer.smooth_move_to(x, y)
        else:
            await page.mouse.move(x, y)
        await page.wait_for_timeout(random.randint(100, 220))
        await page.mouse.down()

        deadline = time.monotonic() + 15  # 进度环最长按住时间
        while time.monotonic() < deadline:
            await page.wait_for_timeout(300)
            if await _passed(page):
                reason = "passed"
                break
            # 「松开」提示出现 → 立即松开
            try:
                if await frame.get_by_text("松开").count() > 0:
                    reason = "release_text"
                    break
            except Exception:
                pass
            # 按钮消失（进度完成/挑战切换）→ 松开
            try:
                if await locator.count() == 0:
                    reason = "button_gone"
                    break
            except Exception:
                pass
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        reason = "exception"
    finally:
        try:
            await page.mouse.up()
        except Exception:
            pass
    return {"box": box, "x": x, "y": y, "held_ms": int((time.monotonic() - started) * 1000), "reason": reason, "error": error}


async def _click(page: Any, humanizer: Any, locator: Any) -> bool:
    if humanizer is not None and hasattr(humanizer, "smooth_click"):
        return await humanizer.smooth_click(locator)
    try:
        await locator.first.click(timeout=5000)
        return True
    except Exception:
        return False


async def _find_press_button(
    page: Any, selector: str
) -> tuple[Any, Any] | None:
    """在所有帧中查找可见的挑战按钮，返回 (locator, frame)。"""
    try:
        frames = list(page.frames)
    except Exception:
        frames = []
    for frame in frames:
        try:
            loc = frame.locator(selector).first
            if await loc.count() > 0 and await loc.is_visible():
                return loc, frame
        except Exception:
            continue
    # 旧版嵌套 iframe 兜底
    try:
        old = (
            page.frame_locator('iframe[title="验证质询"]')
            .frame_locator('iframe[style*="display: block"]')
            .locator(selector)
            .first
        )
        if await old.count() > 0 and await old.is_visible():
            return old, page.frame_locator('iframe[title="验证质询"]').frame_locator(
                'iframe[style*="display: block"]'
            )
    except Exception:
        pass
    return None


def _button_frames(page: Any) -> list[Any]:
    """返回所有可能承载挑战按钮的帧。

    新版 Arkose HUMAN：按钮渲染在 ch_ctx 帧内嵌 iframe 创建的
    about:blank 子帧中（URL 不固定），因此遍历全部帧；
    旧版：iframe[title="验证质询"] → 内层 iframe。
    """
    out = []
    try:
        out = list(page.frames)
    except Exception:
        pass
    return out


async def _wait_challenge_ready(page: Any, press_selector: str, timeout_ms: int) -> bool:
    """等待 Arkose 挑战按钮渲染出现（按钮可能比 iframe 晚几秒才进 #px-captcha）。

    覆盖：新版 ch_ctx 帧 / hsprotect 容器帧 / 旧版嵌套 iframe 中的按钮。
    """
    deadline = time.monotonic() + timeout_ms / 1000
    all_selectors = f'[aria-label="可访问性挑战"], {press_selector}'
    while time.monotonic() < deadline:
        if await _passed(page):
            return True
        try:
            for frame in _button_frames(page):
                if await frame.locator(all_selectors).count() > 0:
                    return True
            old_f2 = (
                page.frame_locator('iframe[title="验证质询"]')
                .frame_locator('iframe[style*="display: block"]')
            )
            if await old_f2.locator(all_selectors).count() > 0:
                return True
        except Exception:
            pass
        await page.wait_for_timeout(1000)
    return False


async def _passed(page: Any) -> bool:
    """挑战通过判定：出现「让我们来保护你的帐户」或辅助邮箱输入框 #EmailAddress。"""
    try:
        if await page.get_by_text("让我们来保护你的帐户").count() > 0:
            return True
        if await page.locator("#EmailAddress").count() > 0:
            return True
    except Exception:
        pass
    return False


async def _keep_going(page: Any) -> bool:
    for frame in list(page.frames):
        try:
            if await frame.get_by_text(
                "Keep going. You might need a few more tries.", exact=True
            ).count() > 0:
                return True
        except Exception:
            continue
    return False


async def _rate_limited(page: Any) -> bool:
    try:
        if await page.get_by_text("一些异常活动").count() > 0:
            return True
        if await page.get_by_text("此站点正在维护，暂时无法使用，请稍后重试。").count() > 0:
            return True
    except Exception:
        pass
    return False


PROVIDER = BrowserPressFuncaptchaProvider()
