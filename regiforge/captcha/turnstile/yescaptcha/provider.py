"""YesCaptcha Turnstile Provider — TurnstileTaskProxyless / TurnstileTaskProxylessM1.

通过 YesCaptcha API 自动解决 Cloudflare Turnstile 挑战。
支持 premium 模式（M1）和标准模式，自动 fallback。

API 文档: https://yescaptcha.atlassian.net/wiki/spaces/YESCAPTCHA/pages/63897603/YesCaptcha+API
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import requests
import urllib3

from core.base import CaptchaProvider

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class YesCaptchaTurnstileProvider(CaptchaProvider):
    """通过 YesCaptcha API 自动解决 Turnstile 挑战（ProxyLess）。

    支持 TurnstileTaskProxyless（标准）和 TurnstileTaskProxylessM1（premium）。
    默认先尝试 premium 再 fallback 到标准。
    """

    type = "turnstile"
    id = "yescaptcha"
    name = "YesCaptcha (Turnstile ProxyLess)"

    # 已知站点 sitekey 兜底
    _KNOWN_SITEKEYS: dict[str, str] = {
        "accounts.x.ai": "0x4AAAAAAAhr9JGVDZbrZOo0",
        "x.ai": "0x4AAAAAAAhr9JGVDZbrZOo0",
        "openai.com": "0x4AAAAAAARfCDXGvVTVqPQi",
        "auth.openai.com": "0x4AAAAAAARfCDXGvVTVqPQi",
        "chatgpt.com": "0x4AAAAAAARfCDXGvVTVqPQi",
    }

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}

    async def solve(self, *, sitekey: str, page_url: str, **kwargs: Any) -> str | None:
        api_key = (self._config.get("api_key") or "").strip()
        if not api_key:
            raise RuntimeError("YesCaptcha api_key 未配置，请在页面配置中填写")

        api_url = (self._config.get("api_url") or "https://api.yescaptcha.com").rstrip("/")
        poll_interval = float(self._config.get("poll_interval") or 3)
        max_poll = int(self._config.get("max_poll") or 60)
        premium = bool(self._config.get("premium", True))
        fallback = bool(self._config.get("fallback", True))

        # sitekey 兜底
        actual_sitekey = sitekey or ""
        if not actual_sitekey:
            page_url_lower = (page_url or "").lower()
            for domain, sk in self._KNOWN_SITEKEYS.items():
                if domain in page_url_lower:
                    actual_sitekey = sk
                    break

        if not actual_sitekey:
            raise RuntimeError("无法获取 Turnstile sitekey，请确保页面上有 turnstile 挂件")

        # 清理 page_url
        clean_url = page_url.split("?", 1)[0].split("#", 1)[0] if page_url else ""

        # 确定任务类型顺序
        task_types: list[str] = []
        if premium:
            task_types.append("TurnstileTaskProxylessM1")
            if fallback:
                task_types.append("TurnstileTaskProxyless")
        else:
            task_types.append("TurnstileTaskProxyless")
            if fallback:
                task_types.append("TurnstileTaskProxylessM1")

        errors: list[str] = []
        for idx, task_type in enumerate(task_types):
            task = {
                "type": task_type,
                "websiteURL": clean_url,
                "websiteKey": actual_sitekey,
            }
            try:
                print(f"[turnstile.yescaptcha] 尝试 {idx+1}/{len(task_types)} type={task_type}", flush=True)
                task_id = await asyncio.to_thread(
                    _create_task, api_key, api_url, task
                )
                token = await asyncio.to_thread(
                    _poll_result, api_key, api_url, task_id,
                    poll_interval, max_poll
                )
                if token:
                    print(f"[turnstile.yescaptcha] Turnstile token 已获取（长度 {len(token)}）", flush=True)
                    return token
            except Exception as exc:
                msg = f"{task_type}: {exc}"
                errors.append(msg)
                print(f"[turnstile.yescaptcha] {msg}", flush=True)
                if idx + 1 < len(task_types):
                    await asyncio.sleep(1.0)
                    continue
                break

        raise RuntimeError(
            "YesCaptcha Turnstile solve failed: " + " | ".join(errors[:4])
        )


def _post_json(api_url: str, path: str, payload: dict, *, timeout: float = 30.0) -> dict:
    """向 YesCaptcha API 发送 POST 请求（强制直连，不走环境变量代理）。

    TurnstileTaskProxyless 任务不依赖客户端 IP。实测经 SOCKS5 代理访问
    api.yescaptcha.com 会 100% SSLEOFError（直连则 12/12 成功），故用
    trust_env=False 屏蔽 HTTPS_PROXY/ALL_PROXY 等环境变量，避免被注册
    代理污染。
    """
    url = f"{api_url}{path}"
    with requests.Session() as s:
        s.trust_env = False
        resp = s.post(url, json=payload, timeout=timeout, verify=False)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"YesCaptcha non-object response: {data!r}")
    return data


def _create_task(api_key: str, api_url: str, task: dict) -> str:
    """创建 YesCaptcha 任务并返回 taskId。"""
    payload = {"clientKey": api_key, "task": task}
    data = _post_json(api_url, "/createTask", payload, timeout=45)
    if data.get("errorId", 0) != 0:
        raise RuntimeError(
            f"YesCaptcha createTask failed: "
            f"{data.get('errorCode')}: {data.get('errorDescription')}"
        )
    task_id = data.get("taskId")
    if not task_id:
        raise RuntimeError(f"YesCaptcha createTask returned no taskId: {data}")
    return str(task_id)


def _poll_result(api_key: str, api_url: str, task_id: str,
                 poll_interval: float, max_poll: int) -> str:
    """轮询 YesCaptcha 任务结果，返回 token 或超时。"""
    payload = {"clientKey": api_key, "taskId": task_id}
    started = time.time()
    for _ in range(max_poll):
        data = _post_json(api_url, "/getTaskResult", payload, timeout=45)
        if data.get("errorId", 0) != 0:
            raise RuntimeError(
                f"YesCaptcha getTaskResult error: "
                f"{data.get('errorCode')}: {data.get('errorDescription')}"
            )
        status = str(data.get("status") or "")
        if status == "ready":
            solution = data.get("solution") or {}
            token = (
                solution.get("token")
                or solution.get("gRecaptchaResponse")
                or solution.get("cf_clearance")
            )
            if not token:
                raise RuntimeError(f"YesCaptcha returned no token: {data}")
            return str(token)
        if status in ("processing", "idle", ""):
            time.sleep(poll_interval)
            continue
        raise RuntimeError(f"YesCaptcha unexpected status: {status}")
    raise TimeoutError(
        f"YesCaptcha task {task_id} did not complete within {max_poll * poll_interval}s"
    )


PROVIDER = YesCaptchaTurnstileProvider()
