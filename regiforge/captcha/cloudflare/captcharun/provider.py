from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import urlparse

import requests
import urllib3

from core.base import CaptchaProvider

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class CaptchaRunCloudflareProvider(CaptchaProvider):
    """通过 CaptchaRun API 解决 Cloudflare 5 秒盾挑战。

    要求：
    - 当前项目必须配置了代理（proxy）以传入 CaptchaRun
    - 调用 solve() 时需要传入 proxy_host / proxy_port / proxy_login / proxy_password
    - 返回 JSON 字符串: {"cf_clearance": "...", "ua": "..."}
    - 调用方负责将 cf_clearance 写入浏览器 Cookie 并设置 UA
    """

    type = "cloudflare"
    id = "captcharun"
    name = "CaptchaRun (CloudFlare5s)"

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}

    async def solve(self, *, sitekey: str, page_url: str, **kwargs: Any) -> str | None:
        api_key = (self._config.get("api_key") or "").strip()
        if not api_key:
            raise RuntimeError("CaptchaRun api_key 未配置，请在页面配置中填写")

        api_url = (self._config.get("api_url") or "https://api.captcha-run.com/v2/tasks").rstrip("/")
        poll_interval = float(self._config.get("poll_interval") or 3)
        max_poll = int(self._config.get("max_poll") or 60)

        # 从 kwargs 取代理信息
        proxy_host = kwargs.get("proxy_host") or ""
        proxy_port = kwargs.get("proxy_port") or 0
        proxy_login = kwargs.get("proxy_login") or ""
        proxy_password = kwargs.get("proxy_password") or ""
        if not proxy_host or not proxy_port:
            raise RuntimeError(
                "cloudflare.captcharun 需要代理信息（proxy_host/proxy_port），"
                "请确保当前项目配置了代理并传入 solve() 的 kwargs"
            )

        payload = {
            "captchaType": "CloudFlare5s",
            "siteReferer": page_url,
            "host": proxy_host,
            "port": int(proxy_port),
            "login": proxy_login,
            "password": proxy_password,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        def create_task() -> str:
            resp = requests.post(api_url, headers=headers, json=payload, timeout=30, verify=False)
            if resp.status_code not in (200, 201):
                raise RuntimeError(f"CaptchaRun CloudFlare5s 创建任务失败: HTTP {resp.status_code} {resp.text[:200]}")
            data = resp.json()
            task_id = data.get("taskId")
            if not task_id:
                raise RuntimeError(f"CaptchaRun CloudFlare5s 响应无 taskId: {data}")
            return task_id

        task_id = await asyncio.to_thread(create_task)

        def poll_once() -> str | None:
            resp = requests.get(f"{api_url}/{task_id}", headers=headers, timeout=15, verify=False)
            if resp.status_code != 200:
                return None
            result = resp.json()
            status = result.get("status", "")
            if status == "Working":
                return None
            if status == "Fail":
                raise RuntimeError(f"CaptchaRun CloudFlare5s 任务失败: {result.get('reason', 'unknown')}")
            response_obj = result.get("response", {})
            if not isinstance(response_obj, dict):
                return None
            cookies = response_obj.get("cookies", {})
            cf_clearance = cookies.get("cf_clearance") if isinstance(cookies, dict) else None
            ua = response_obj.get("ua", "")
            if not cf_clearance:
                return None
            return json.dumps({"cf_clearance": cf_clearance, "ua": ua}, ensure_ascii=False)

        for _ in range(max_poll):
            await asyncio.sleep(poll_interval)
            result = await asyncio.to_thread(poll_once)
            if result:
                return result
        return None


PROVIDER = CaptchaRunCloudflareProvider()