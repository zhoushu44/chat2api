"""mihomo (Mihomo-Relay-WebUI) 代理 Provider。

通过服务器 7892 端口的 WebUI API 拉取当前对外连接入口（SOCKS5/HTTP），
适用于模式 E「API 提取」等由 mihomo 服务端自动切换上游代理的场景。

API 接口：
- GET  /api/status?key=KEY       状态（alive / country / ip / mode / sticky_enabled）
- GET  /api/connections?key=KEY  对外连接入口（SOCKS5 7890 / HTTP 7891，含账号密码 URL）
- POST /api/rotate?key=KEY       轮换/刷新（可选，由 mihomo 按场景自动处理时可不开）

配置字段：
- api_base     必填，如 http://192.6.121.16:7892
- api_key      必填，WebUI API Key
- protocol     返回的入口协议：socks5（默认）或 http
- rotate       每次 acquire 是否先调用 /api/rotate 换新出口 IP（默认 false；
               模式 E 由服务端每 2 分钟自动提取，通常无需每账号轮换）

SOCKS5 凭据兼容：mihomo 7890 通常启用 RFC1929 用户名密码认证，但 Playwright/Patchright
的 Chromium 通过 `--proxy-server=socks5://host:port` 拨号时不携带凭据，会触发
`net::ERR_SOCKS_CONNECTION_FAILED` → step01 122s 超时。`acquire()` 末尾会自动
检测带凭据的 socks 入口并启动本地 HTTP CONNECT 转发器，让 Chrome 连
`http://127.0.0.1:<port>`，由转发器带凭据连上游 socks5；启动失败回退
`socks5h://user:pass@host:port`（仅 curl_cffi/requests 兼容，浏览器链路仍会
失败）。
"""
from __future__ import annotations

from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from core.base import ProxyProvider
from core.models import ProxyInfo


class MihomoProvider(ProxyProvider):
    """mihomo WebUI 代理 Provider。"""

    id = "mihomo"
    name = "mihomo API（动态出口）"

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}

    async def _request(self, method: str, path: str) -> dict[str, Any]:
        api_base = str(self._config.get("api_base") or "").strip().rstrip("/")
        api_key = str(self._config.get("api_key") or "").strip()
        if not api_base or not api_key:
            raise RuntimeError("mihomo 代理缺少 api_base 或 api_key 配置")
        url = f"{api_base}{path}"
        params = {"key": api_key}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.request(method, url, params=params)
            resp.raise_for_status()
            data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"mihomo API 返回异常：{data}")
        return data

    async def acquire(self) -> ProxyInfo | None:
        """从 /api/connections 拉取当前对外入口并返回 ProxyInfo。"""
        protocol = str(self._config.get("protocol") or "socks5").strip().lower()
        if protocol not in {"socks5", "http"}:
            protocol = "socks5"

        if self._config.get("rotate"):
            await self._request("POST", "/api/rotate")

        data = await self._request("GET", "/api/connections")
        conns = data.get("connections") or {}

        # 选择入口：socks -> socks5://，http -> http(s)://
        target = conns.get("socks") if protocol == "socks5" else conns.get("http")
        if not target:
            raise RuntimeError(f"mihomo 未启用 {protocol} 对外入口")
        url = target.get("url")
        if not url:
            raise RuntimeError("mihomo connections 缺少 url")
        if not target.get("enabled"):
            raise RuntimeError(f"mihomo {protocol} 对外入口未启用")

        info = ProxyInfo(
            server=url,
            username=target.get("username") or None,
            password=target.get("password") or None,
            meta={
                "source": self.id,
                "host": target.get("host"),
                "port": target.get("port"),
                "protocol": protocol,
            },
        )
        # Chrome 不支持 SOCKS5 认证：带凭据时启动本地 HTTP 转发器
        return self._with_auth_forwarder(info)

    def _with_auth_forwarder(self, proxy_info: ProxyInfo | None) -> ProxyInfo | None:
        """带认证的 SOCKS5 上游 → 本地 HTTP 转发器（避免 Chrome 拨号失败）。

        与 proxy/wary 的等价逻辑：playwright/patchright 的 Chrome --proxy-server 不支持
        SOCKS5 RFC1929 用户名密码认证。mihomo 7890 启用凭据后必须先起一个本地 HTTP
        CONNECT 转发器，让 Chrome 连 127.0.0.1 的 HTTP 端口，再由转发器带上凭据
        连上游 socks5。启动转发器失败时回退 socks5h://user:pass@host:port（仅
        curl_cffi / requests 能用，浏览器链路会 ERR_SOCKS_CONNECTION_FAILED）。
        """
        if proxy_info is None:
            return None
        parsed = urlparse(proxy_info.server)
        username = proxy_info.username or (unquote(parsed.username) if parsed.username else None)
        password = proxy_info.password or (unquote(parsed.password) if parsed.password else None)
        if (not username and not password) or not parsed.hostname or not parsed.port:
            return proxy_info

        try:
            from proxy.socks5.http_forwarder import Socks5HttpForwarder

            forwarder = Socks5HttpForwarder(
                remote_host=parsed.hostname,
                remote_port=parsed.port,
                username=username or "",
                password=password or "",
            )
            local_server = forwarder.start_sync()
            return ProxyInfo(
                server=local_server,
                username=None,
                password=None,
                meta={**proxy_info.meta, "upstream": proxy_info.server},
            )
        except Exception as exc:
            user = username or ""
            pwd = password or ""
            netloc = f"{user}:{pwd}@{parsed.hostname}:{parsed.port}"
            return ProxyInfo(
                server=f"socks5h://{netloc}",
                username=user,
                password=pwd,
                meta={**proxy_info.meta, "forwarder_fallback": str(exc)},
            )

    def meta(self) -> dict[str, Any]:
        base = super().meta()
        base["api_base"] = str(self._config.get("api_base") or "").strip()
        return base


PROVIDER = MihomoProvider()
