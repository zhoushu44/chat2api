from __future__ import annotations

import asyncio
import base64
from typing import Any

from core.base import CaptchaProvider


class SensenovaSliderProvider(CaptchaProvider):
    type = "slider"
    id = "sensenova"
    name = "SenseNova 图片滑块"

    async def solve(self, *, sitekey: str, page_url: str, **kwargs: Any) -> str | None:
        return await asyncio.to_thread(self._solve_sync, kwargs)

    def _solve_sync(self, kwargs: dict[str, Any]) -> str | None:
        try:
            import cv2
            import numpy as np
        except ImportError as exc:
            raise RuntimeError("SenseNova 滑块需要安装 opencv-python-headless 和 numpy") from exc

        session = kwargs["session"]
        proxies = kwargs.get("proxies")
        iam_base = kwargs["iam_base"]
        for _ in range(5):
            response = session.get(
                f"{iam_base}/auth/getCaptcha", proxies=proxies, timeout=15,
            )
            response.raise_for_status()
            data = response.json()
            code_key = data.get("code_key", "")
            if not code_key:
                continue
            bg = cv2.imdecode(np.frombuffer(base64.b64decode(data.get("image", "")), np.uint8), cv2.IMREAD_COLOR)
            block = cv2.imdecode(np.frombuffer(base64.b64decode(data.get("block", "")), np.uint8), cv2.IMREAD_UNCHANGED)
            if bg is None or block is None:
                continue
            bg_edge = cv2.Canny(cv2.cvtColor(bg, cv2.COLOR_BGR2GRAY), 100, 200)
            block_edge = cv2.Canny(cv2.cvtColor(block[:, :, :3], cv2.COLOR_BGR2GRAY), 100, 200)
            result = cv2.matchTemplate(bg_edge, block_edge, cv2.TM_CCOEFF_NORMED)
            x = cv2.minMaxLoc(result)[3][0]
            check = session.get(
                f"{iam_base}/auth/checkCaptcha",
                params={"code_key": code_key, "code_value": str(x)},
                proxies=proxies, timeout=10,
            )
            check.raise_for_status()
            if check.json().get("result"):
                return code_key
        return None


PROVIDER = SensenovaSliderProvider()
