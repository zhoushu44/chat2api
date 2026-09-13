from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlparse

import requests
import urllib3

from core.base import CaptchaProvider

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class CaptchaRunHCaptchaProvider(CaptchaProvider):
    type = "hcaptcha"
    id = "captcharun"
    name = "CaptchaRun"

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}

    async def solve(self, *, sitekey: str, page_url: str, **kwargs: Any) -> str | None:
        api_key = (self._config.get("api_key") or "").strip()
        if not api_key:
            raise RuntimeError("CaptchaRun api_key 未配置，请在页面配置中填写")

        api_url = (self._config.get("api_url") or "https://api.captcha-run.com/v2/tasks").rstrip("/")
        poll_interval = float(self._config.get("poll_interval") or 3)
        max_poll = int(self._config.get("max_poll") or 60)

        parsed = urlparse(page_url)
        site_referer = f"{parsed.scheme}://{parsed.netloc}/"
        payload = {
            "captchaType": "HCaptcha",
            "siteKey": sitekey,
            "siteReferer": site_referer,
            "fallbackToActualUA": True,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        def create_task() -> str:
            # captcha-run.com 偶发 SSL EOF（UNEXPECTED_EOF_WHILE_READING），重试 3 次
            import time as _t
            last_err: Exception | None = None
            for attempt in range(3):
                try:
                    resp = requests.post(api_url, headers=headers, json=payload, timeout=30, verify=False)
                    if resp.status_code not in (200, 201):
                        raise RuntimeError(f"CaptchaRun 创建任务失败: HTTP {resp.status_code} {resp.text[:200]}")
                    data = resp.json()
                    task_id = data.get("taskId")
                    if not task_id:
                        raise RuntimeError(f"CaptchaRun 响应无 taskId: {data}")
                    return task_id
                except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as e:
                    last_err = e
                    if attempt < 2:
                        _t.sleep(3)
            raise last_err  # type: ignore[misc]

        task_id = await asyncio.to_thread(create_task)

        def poll_once() -> str | None:
            # 轮询偶发 SSL EOF（UNEXPECTED_EOF_WHILE_READING），返回 None 让外层继续轮询
            # 而不是抛异常杀死整个 task（task 已创建，浪费配额）
            try:
                proxy = self._config.get("proxy")
                proxies = {"http": proxy, "https": proxy} if proxy else None
                resp = requests.get(f"{api_url}/{task_id}", headers=headers, timeout=15, verify=False, proxies=proxies)
            except (requests.exceptions.SSLError, requests.exceptions.ConnectionError):
                return None
            if resp.status_code != 200:
                return None
            result = resp.json()
            status = result.get("status", "")
            if status == "Working":
                return None
            if status == "Fail":
                raise RuntimeError(f"CaptchaRun 任务失败: {result.get('reason', 'unknown')}")
            response_obj = result.get("response", {})
            token = response_obj.get("gRecaptchaResponse") if isinstance(response_obj, dict) else None
            if not token:
                token = (
                    result.get("gRecaptchaResponse")
                    or result.get("token")
                    or (result.get("solution") or {}).get("gRecaptchaResponse")
                )
            return token

        for _ in range(max_poll):
            await asyncio.sleep(poll_interval)
            token = await asyncio.to_thread(poll_once)
            if token:
                return token
        return None


PROVIDER = CaptchaRunHCaptchaProvider()
