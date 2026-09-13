from __future__ import annotations

from core.base import ProxyProvider
from core.models import ProxyInfo


class NoneProxyProvider(ProxyProvider):
    id = "none"
    name = "直连（无代理）"

    async def acquire(self) -> ProxyInfo | None:
        return None


PROVIDER = NoneProxyProvider()
