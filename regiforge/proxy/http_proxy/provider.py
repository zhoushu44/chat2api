"""HTTP/HTTPS 代理 Provider - 支持带认证的 http:// 和 https:// 代理。

用于 ChatGPT HTTP 注册模式（curl_cffi）以及其他需要 HTTP 代理的场景。
"""
from __future__ import annotations

import random
import re
from typing import Any
from urllib.parse import urlparse

from core.base import ProxyProvider
from core.models import ProxyInfo


class HttpProxyProvider(ProxyProvider):
    """HTTP/HTTPS 代理 Provider。

    支持：
    - 单行/多行 http:// 或 https:// 代理（自动轮换）
    - 带认证：http://user:pass@host:port
    - 无认证：http://host:port

    轮换机制：
    - _proxy_pool: 存储所有配置的代理地址
    - _proxy_index: 当前代理索引，每次 acquire() 递增
    - _failed_proxies: 失败代理集合，轮换时自动跳过
    """

    id = "http_proxy"
    name = "HTTP/HTTPS 代理（多行轮换）"

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}
        self._proxy_pool: list[str] = []
        self._proxy_index: int = 0
        self._failed_proxies: set[str] = set()

    async def acquire(self) -> ProxyInfo | None:
        """获取代理。

        支持两种模式：
        1. 多行轮换模式：手动配置多个代理地址，自动轮换
        2. 直连模式：留空时直连
        """
        server_config = str(self._config.get("server") or "").strip()
        if not server_config:
            return None

        # 支持多行输入，每行一个代理地址
        proxy_lines = [line.strip() for line in server_config.split("\n") if line.strip()]
        if not proxy_lines:
            return None

        # 轮换使用代理
        if not self._proxy_pool:
            self._proxy_pool = proxy_lines
            self._proxy_index = 0

        # 获取下一个可用代理
        for _ in range(len(self._proxy_pool)):
            proxy_str = self._proxy_pool[self._proxy_index % len(self._proxy_pool)]
            self._proxy_index += 1

            if proxy_str in self._failed_proxies:
                continue

            proxy_info = self._normalize_proxy(proxy_str)
            return proxy_info

        return None

    async def release(self, proxy: ProxyInfo, failure_type: str | None = None) -> None:
        """释放代理（将失败代理加入黑名单）。"""
        if proxy and proxy.server in self._failed_proxies:
            # 已经在失败集合中，保持
            pass

    def _normalize_proxy(self, proxy_str: str) -> ProxyInfo:
        """标准化代理地址为 ProxyInfo。

        支持格式：
        - http://user:pass@host:port
        - https://user:pass@host:port
        - http://host:port
        - https://host:port
        """
        proxy_str = proxy_str.strip()

        # 验证协议前缀
        lower = proxy_str.lower()
        if not (lower.startswith("http://") or lower.startswith("https://")):
            # 自动添加 http:// 前缀
            proxy_str = f"http://{proxy_str}"

        parsed = urlparse(proxy_str)
        if not parsed.hostname or not parsed.port:
            raise ValueError(f"无效的 HTTP 代理格式：{proxy_str}（缺少主机或端口）")

        return ProxyInfo(
            server=proxy_str,
            username=parsed.username,
            password=parsed.password,
            meta={"source": "http_proxy", "host": parsed.hostname, "port": parsed.port, "scheme": parsed.scheme},
        )

    def meta(self) -> dict[str, Any]:
        base = super().meta()
        base["proxy_count"] = len(self._proxy_pool)
        base["failed_count"] = len(self._failed_proxies)
        return base


PROVIDER = HttpProxyProvider()
