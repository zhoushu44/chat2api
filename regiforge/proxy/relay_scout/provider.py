"""Relay Scout SOCKS5 代理池 Provider。"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from core.base import ProxyProvider
from core.models import ProxyInfo


class RelayScoutProvider(ProxyProvider):
    id = "relay_scout"
    name = "Relay Scout 代理池（API）"

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}

    async def acquire(self) -> ProxyInfo | None:
        base_url = str(self._config.get("base_url") or "").strip().rstrip("/")
        project = str(self._config.get("project") or "default").strip()
        api_key = str(self._config.get("api_key") or "").strip()
        session = str(self._config.get("session") or "").strip()
        if not base_url or not project or not api_key:
            raise RuntimeError("Relay Scout 代理缺少 base_url、project 或 api_key 配置")

        params = {"project": project, "key": api_key, "format": "txt"}
        if session:
            params["session"] = session
        async with httpx.AsyncClient(timeout=float(self._config.get("timeout") or 15)) as client:
            try:
                response = await client.get(f"{base_url}/api/v1/proxy", params=params)
                response.raise_for_status()
            except Exception as exc:
                raise RuntimeError(f"Relay Scout 代理 API 请求失败：{exc}") from exc

        proxy_url = response.text.strip().splitlines()[0] if response.text.strip() else ""
        parsed = urlparse(proxy_url)
        if not parsed.hostname or not parsed.port:
            raise RuntimeError(f"Relay Scout 返回无效代理地址：{proxy_url}")
        return ProxyInfo(
            server=proxy_url,
            username=parsed.username,
            password=parsed.password,
            meta={
                "source": self.id,
                "project": project,
                "session": session or None,
                "host": parsed.hostname,
                "port": parsed.port,
                "scheme": parsed.scheme,
            },
        )

    def meta(self) -> dict[str, Any]:
        base = super().meta()
        base["base_url"] = str(self._config.get("base_url") or "").strip()
        base["project"] = str(self._config.get("project") or "default").strip()
        return base


PROVIDER = RelayScoutProvider()
