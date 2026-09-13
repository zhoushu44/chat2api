from __future__ import annotations

import asyncio
import base64
import math
import random
import re
from typing import Any

import requests

from core.base import CaptchaProvider


class AliyunSliderProvider(CaptchaProvider):
    type = "slider"
    id = "aliyun"
    name = "阿里云图片滑块"

    async def solve(self, *, sitekey: str, page_url: str, **kwargs: Any) -> str | None:
        page = kwargs.get("page")
        if page is None:
            raise RuntimeError("阿里云 slider captcha 需要 Playwright page")

        config = getattr(self, "_config", {}) or {}
        max_retries = max(1, int(config.get("max_retries") or 3))
        timeout = max(5, float(kwargs.get("timeout") or 30))
        image = page.locator("#aliyunCaptcha-img")
        puzzle = page.locator("#aliyunCaptcha-puzzle")
        slider = page.locator("#aliyunCaptcha-sliding-slider")

        # 部分站点先出现「点击开始验证」入口按钮，img 仍隐藏，需点击展开弹层。
        # 弹层打开后（window-float 非 none）就停止点击入口，避免重复点击把弹层再收起。
        for _ in range(int(timeout)):
            if await image.count() and await image.is_visible():
                break
            expanded = await page.evaluate(
                """() => {
                    const win = document.getElementById('aliyunCaptcha-window-float');
                    if (!win) return false;
                    if (win.className.includes('window-hidden')) return false;
                    return getComputedStyle(win).display !== 'none';
                }"""
            )
            if expanded:
                await page.wait_for_timeout(500)
                continue
            start_btn = page.locator("#aliyunCaptcha-captcha-text-box")
            if not (await start_btn.count() and await start_btn.is_visible()):
                start_btn = page.locator("text=点击开始验证").first
            if await start_btn.count() and await start_btn.is_visible():
                try:
                    await start_btn.click(timeout=2000)
                except Exception:
                    pass
            await page.wait_for_timeout(800)

        try:
            await image.wait_for(state="visible", timeout=int(timeout * 1000))
            await puzzle.wait_for(state="visible", timeout=5000)
            await slider.wait_for(state="visible", timeout=5000)
        except Exception as exc:
            raise RuntimeError("阿里云 slider captcha 元素未出现") from exc

        for attempt in range(max_retries):
            bg_url = await image.get_attribute("src")
            puzzle_url = await puzzle.get_attribute("src")
            if not bg_url or not puzzle_url:
                await self._refresh(page)
                continue

            bg_bytes, puzzle_bytes = await asyncio.gather(
                self._download(page, bg_url, page_url),
                self._download(page, puzzle_url, page_url),
            )
            gap_x = await asyncio.to_thread(self._find_gap, bg_bytes, puzzle_bytes, config)
            if gap_x <= 0:
                await self._refresh(page)
                continue

            # 标准阿里云滑块（如 chat.z.ai）直接使用图像缺口像素距离；
            # tokenrhythm 等站点存在镜头畸变，需用 drag_distance 换算。
            use_raw = bool(config.get("raw_gap") or kwargs.get("raw_gap"))
            distance = gap_x if use_raw else self.drag_distance(gap_x)
            if await self._drag(page, slider, distance) and await self._verified(page):
                return f"aliyun:{attempt + 1}"
            await self._refresh(page)
        return None

    @staticmethod
    def drag_distance(puzzle_x: float) -> int:
        a = 0.003550
        b = 0.076971
        return int((-b + math.sqrt(b * b + 4 * a * puzzle_x)) / (2 * a))

    async def _download(self, page: Any, url: str, referer: str) -> bytes:
        # 部分站点（如 chat.z.ai）直接内嵌 base64 data URI，无需 HTTP 下载
        if url.startswith("data:"):
            import base64 as _b64

            payload = url.split(",", 1)[-1]
            if "base64" in url.split(",", 1)[0]:
                return _b64.b64decode(payload)
            return payload.encode("utf-8")
        response = await page.context.request.get(
            url,
            headers={"Referer": referer or "https://tokenrhythm.studio/"},
            timeout=15_000,
        )
        if not response.ok:
            raise RuntimeError(f"阿里云 slider captcha 图片下载失败: HTTP {response.status}")
        return await response.body()

    def _find_gap(self, bg_bytes: bytes, puzzle_bytes: bytes, config: dict[str, Any]) -> int:
        gap = self._find_gap_yydsocr(bg_bytes, puzzle_bytes, config)
        return gap or self._find_gap_opencv(bg_bytes, puzzle_bytes)

    @staticmethod
    def _find_gap_yydsocr(bg_bytes: bytes, puzzle_bytes: bytes, config: dict[str, Any]) -> int:
        api_url = str(config.get("api_url") or "").strip()
        secret_key = str(config.get("secret_key") or "").strip()
        if not api_url or not secret_key:
            return 0
        payload = {
            "secret_key": secret_key,
            "type_id": str(config.get("type_id") or "20040"),
            "background_image": base64.b64encode(bg_bytes).decode(),
            "slide_image": base64.b64encode(puzzle_bytes).decode(),
        }
        try:
            response = requests.post(api_url, json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()
            if str(result.get("code")) != "200":
                return 0
            text = str((result.get("data") or {}).get("data") or "")
            match = re.search(r"\d+", text)
            gap = int(match.group()) if match else 0
            return gap if 20 < gap < 300 else 0
        except Exception:
            return 0

    @staticmethod
    def _find_gap_opencv(bg_bytes: bytes, puzzle_bytes: bytes) -> int:
        try:
            import cv2
            import numpy as np

            bg = cv2.imdecode(np.frombuffer(bg_bytes, np.uint8), cv2.IMREAD_COLOR)
            piece = cv2.imdecode(np.frombuffer(puzzle_bytes, np.uint8), cv2.IMREAD_UNCHANGED)
            if bg is None or piece is None:
                return 0
            if piece.ndim == 3 and piece.shape[2] == 4:
                alpha = piece[:, :, 3]
                coords = cv2.findNonZero(alpha)
                if coords is not None:
                    x, y, width, height = cv2.boundingRect(coords)
                    piece = piece[y:y + height, x:x + width]
                piece = cv2.cvtColor(piece, cv2.COLOR_BGRA2BGR)
            width = piece.shape[1]
            search_start = width + 20
            result = cv2.matchTemplate(bg[:, search_start:], piece, cv2.TM_CCOEFF_NORMED)
            _, confidence, _, location = cv2.minMaxLoc(result)
            gap = location[0] + search_start + width // 2
            return gap if confidence > 0.2 and 20 < gap < 300 else 0
        except Exception:
            return 0

    @staticmethod
    async def _drag(page: Any, slider: Any, distance: int) -> bool:
        box = await slider.bounding_box()
        if not box:
            return False
        start_x = box["x"] + box["width"] / 2
        start_y = box["y"] + box["height"] / 2
        # 从随机位置接近滑块，模拟人手
        await page.mouse.move(start_x + random.uniform(-6, 6), start_y + random.uniform(-40, 40), steps=random.randint(4, 9))
        await page.mouse.move(start_x, start_y)
        await page.wait_for_timeout(random.randint(120, 320))
        await page.mouse.down()
        steps = random.randint(24, 34)
        # 带轻微过冲 + 回拉的拟人轨迹
        overshoot = distance * random.uniform(0.04, 0.10)
        for index in range(1, steps + 1):
            progress = index / steps
            if progress < 0.75:
                eased = (progress / 0.75) ** 1.7  # 加速段
            else:
                tail = (progress - 0.75) / 0.25
                eased = 1 - (1 - tail) ** 2.2  # 减速段
            x = start_x + (distance + overshoot) * eased
            if index == steps:
                x = start_x + distance  # 回拉到目标距离
            await page.mouse.move(x, start_y + random.uniform(-1.5, 1.5))
            await page.wait_for_timeout(random.randint(16, 40))
        await page.wait_for_timeout(random.randint(150, 350))
        await page.mouse.up()
        return True

    @staticmethod
    async def _verified(page: Any) -> bool:
        for _ in range(15):
            state = await page.evaluate("""() => {
                const text = document.getElementById('aliyunCaptcha-sliding-text');
                const value = (text?.textContent || '').trim();
                if (text?.className.includes('verified') || /验证通过|通过成功/.test(value)) return 'passed';
                const success = document.getElementById('aliyunCaptcha-success');
                if (success && /通过|成功/.test(success.textContent || '')) return 'passed';
                const popup = document.getElementById('aliyunCaptcha-window-popup');
                const mask = document.getElementById('aliyunCaptcha-mask');
                const hidden = (node) => node && (node.hidden || getComputedStyle(node).display === 'none' ||
                    node.className.includes('hidden') || node.className.includes('aliyunCaptcha-hidden'));
                if (hidden(popup) || hidden(mask)) return 'passed';
                if (/失败|拖动/.test(value)) return 'failed';
                return '';
            }""")
            if state == "passed":
                return True
            if state == "failed":
                return False
            await page.wait_for_timeout(500)
        return False

    @staticmethod
    async def _refresh(page: Any) -> None:
        await page.evaluate("""() => {
            const button = document.getElementById('aliyunCaptcha-btn-refresh') ||
                document.querySelector('.aliyunCaptcha-refresh, [class*="refresh"]');
            if (button) button.click();
        }""")
        await page.wait_for_timeout(1200)


PROVIDER = AliyunSliderProvider()
