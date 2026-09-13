"""FlareSolverr Provider - 通过 FlareSolverr 服务绕过 Cloudflare 挑战。

FlareSolverr 是一个无头浏览器服务，专门用于绕过 Cloudflare 的 5 秒盾和 JS 挑战。
文档：https://github.com/FlareSolverr/FlareSolverr

使用方式：
    from captcha.cloudflare.flaresolverr.provider import FlareSolverrProvider

    provider = FlareSolverrProvider()
    provider.configure({
        "api_url": "http://192.6.121.16:8191/v1",
        "proxy": {
            "url": "socks5://mihomo:7890",
            "username": "user",  # 可选
            "password": "pass"   # 可选
        },
        "max_timeout": 60000
    })

    result = await provider.solve(
        sitekey="xxx",
        page_url="https://example.com"
    )
    # result: {"cf_clearance": "...", "ua": "...", "cookies": [...]}
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import requests
import urllib3

from core.base import CaptchaProvider

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# PROVIDER 常量，供 __init__.py 导入
PROVIDER = "FlareSolverrProvider"


class FlareSolverrProvider(CaptchaProvider):
    """FlareSolverr Provider - 通过 FlareSolverr 服务解决 Cloudflare 挑战。

    特点：
    - 支持远程 FlareSolverr 服务
    - 可选配合 mihomo 代理使用
    - 返回完整的 Cookie、User-Agent 和页面内容
    - 适用于所有需要过 Cloudflare 的项目

    配置项：
    - api_url: FlareSolverr API 地址，默认 http://127.0.0.1:8191/v1
    - proxy: 代理配置（可选），格式 {"url": "socks5://...", "username": "...", "password": "..."}
    - max_timeout: 最大超时时间（毫秒），默认 60000
    - request_type: 请求类型，可选 "request.get"（默认）或 "browser.get"
    """

    type = "cloudflare"
    id = "flaresolverr"
    name = "FlareSolverr (远程服务)"

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}
        self._session = requests.Session()

    def configure(self, config: dict[str, Any] | None = None) -> None:
        """配置 FlareSolverr 服务地址和参数。

        Args:
            config: 配置字典，包含：
                - api_url: FlareSolverr API 地址
                - proxy: 代理配置（可选）
                - max_timeout: 最大超时（毫秒）
                - request_type: 请求类型
        """
        self._config = config or {}

    async def solve(
        self,
        *,
        sitekey: str = "",
        page_url: str,
        **kwargs: Any,
    ) -> str | None:
        """调用 FlareSolverr 解决 Cloudflare 挑战。

        Args:
            sitekey: Cloudflare sitekey（可选，某些模式需要）
            page_url: 目标页面 URL
            **kwargs: 额外参数，可覆盖配置：
                - api_url: 覆盖 API 地址
                - proxy: 覆盖代理配置
                - max_timeout: 覆盖超时时间

        Returns:
            JSON 字符串，包含：
                - cf_clearance: Cloudflare clearance Cookie
                - ua: User-Agent
                - cookies: 完整 Cookie 列表
                - response: 页面 HTML（可选）
            失败返回 None
        """
        # 合并配置和运行时参数
        api_url = kwargs.get("api_url") or self._config.get("api_url") or "http://127.0.0.1:8191/v1"
        max_timeout = int(kwargs.get("max_timeout") or self._config.get("max_timeout") or 60000)
        proxy_config = kwargs.get("proxy") or self._config.get("proxy")
        request_type = self._config.get("request_type") or "request.get"

        # 构建请求体
        payload = {
            "cmd": request_type,
            "url": page_url,
            "maxTimeout": max_timeout,
        }

        # 添加代理配置（可选）
        if proxy_config:
            proxy_payload = {}
            if isinstance(proxy_config, dict):
                proxy_url = proxy_config.get("url")
                if proxy_url:
                    proxy_payload["url"] = proxy_url
                if proxy_config.get("username"):
                    proxy_payload["username"] = proxy_config["username"]
                if proxy_config.get("password"):
                    proxy_payload["password"] = proxy_config["password"]
            elif isinstance(proxy_config, str):
                proxy_payload["url"] = proxy_config

            if proxy_payload:
                payload["proxy"] = proxy_payload

        # 调用 FlareSolverr API
        try:
            result = await asyncio.to_thread(
                self._call_api,
                api_url,
                payload,
                max_timeout // 1000 + 30,  # 转换为秒并增加缓冲
            )

            if not result:
                return None

            # 提取关键信息
            solution = result.get("solution", {})
            cookies = solution.get("cookies", [])

            # 查找 cf_clearance Cookie
            cf_clearance = None
            for cookie in cookies:
                if isinstance(cookie, dict) and cookie.get("name") == "cf_clearance":
                    cf_clearance = cookie.get("value")
                    break

            # 如果没有 cf_clearance，尝试从其他 Cookie 字段查找
            if not cf_clearance:
                for cookie in cookies:
                    if isinstance(cookie, dict) and "cf_" in cookie.get("name", "").lower():
                        cf_clearance = cookie.get("value")
                        break

            user_agent = solution.get("userAgent", "")

            if not cf_clearance and not user_agent:
                return None

            # 返回结构化结果
            return json.dumps(
                {
                    "cf_clearance": cf_clearance or "",
                    "ua": user_agent,
                    "cookies": cookies,
                    "response": solution.get("response", ""),
                    "url": solution.get("url", page_url),
                    "status": solution.get("status", 200),
                },
                ensure_ascii=False,
            )

        except Exception as e:
            # 打印错误信息用于调试
            import sys
            print(f"FlareSolverr 调用失败：{e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
            # 静默失败，由调用方处理
            return None

    def _call_api(
        self,
        api_url: str,
        payload: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any] | None:
        """同步调用 FlareSolverr API。

        Args:
            api_url: FlareSolverr API 地址
            payload: 请求体
            timeout: 超时时间（秒）

        Returns:
            API 响应字典，失败返回 None

        Raises:
            RuntimeError: API 调用失败时抛出
        """
        try:
            response = self._session.post(
                api_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=timeout,
                verify=False,  # FlareSolverr 通常使用 HTTP 或自签名证书
            )

            if response.status_code != 200:
                raise RuntimeError(
                    f"FlareSolverr API 返回 HTTP {response.status_code}: {response.text[:200]}"
                )

            data = response.json()
            status = data.get("status", "")
            message = data.get("message", "")

            if status != "ok":
                # 检查是否是挑战失败
                if "challenge" in message.lower() or "captcha" in message.lower():
                    raise RuntimeError(f"FlareSolverr 挑战失败：{message}")
                # 其他错误
                raise RuntimeError(f"FlareSolverr 服务错误：{message or 'Unknown error'}")

            return data

        except requests.exceptions.Timeout:
            raise RuntimeError(
                f"FlareSolverr API 超时（{timeout}秒），请检查服务是否正常运行"
            )
        except requests.exceptions.ConnectionError:
            raise RuntimeError(
                f"无法连接到 FlareSolverr 服务 ({api_url})，请检查服务地址和网络"
            )
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"FlareSolverr API 调用失败：{e}")

    def meta(self) -> dict[str, Any]:
        """返回 Provider 元数据。

        Returns:
            包含 Provider 信息的字典
        """
        meta = super().meta()
        meta["config"] = {
            "api_url": self._config.get("api_url", "http://127.0.0.1:8191/v1"),
            "has_proxy": bool(self._config.get("proxy")),
            "max_timeout": self._config.get("max_timeout", 60000),
            "request_type": self._config.get("request_type", "request.get"),
        }
        return meta
