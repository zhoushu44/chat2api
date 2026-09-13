"""Clash 代理 Provider - 通过 Clash API 动态获取代理节点。

适用于需要频繁切换代理 IP 的场景，如批量注册。
"""
from __future__ import annotations

import httpx
from core.base import ProxyProvider
from core.models import ProxyInfo


class ClashProvider(ProxyProvider):
    """Clash 代理 Provider。

    通过 Clash API 获取当前选中的代理节点，转换为 socks5:// 格式。

    配置字段：
    - clash_api_url: Clash API 地址，如 http://127.0.0.1:9090
    - clash_api_secret: Clash API 密钥（可选）
    - clash_group_name: 代理组名称，不填则使用第一个
    - clash_local_port: 本地 SOCKS5 端口，默认 7897

    使用方式：
    1. 确保本地 Clash 客户端已启动并开启了 API
    2. 配置 clash_api_url 和 clash_api_secret
    3. 系统会自动获取当前选中的代理节点
    """

    id = "clash"
    name = "Clash（API 动态节点）"

    def __init__(self) -> None:
        self._config: dict[str, str] = {}

    async def acquire(self) -> ProxyInfo | None:
        """从 Clash API 获取当前代理节点。

        返回格式：socks5://127.0.0.1:7897
        """
        api_url = str(self._config.get("clash_api_url") or "").strip()
        if not api_url:
            return None

        api_secret = str(self._config.get("clash_api_secret") or "").strip()
        group_name = str(self._config.get("clash_group_name") or "").strip()
        local_port = int(self._config.get("clash_local_port") or 7897)

        headers = {}
        if api_secret:
            headers["Authorization"] = f"Bearer {api_secret}"

        async with httpx.AsyncClient(timeout=10, headers=headers) as client:
            try:
                # 获取代理组信息
                groups_resp = await client.get(f"{api_url}/proxies")
                groups_resp.raise_for_status()
                groups_data = groups_resp.json()

                # 选择代理组
                target_group = None
                if group_name and group_name in groups_data.get("proxies", {}):
                    target_group = groups_data["proxies"][group_name]
                else:
                    # 使用第一个代理组
                    for proxy in groups_data.get("proxies", {}).values():
                        if proxy.get("all"):
                            target_group = proxy
                            break

                if not target_group:
                    return None

                # 获取当前选中的节点
                now_node = target_group.get("now")
                if not now_node:
                    return None

                # 返回本地 SOCKS5 代理地址
                return ProxyInfo(
                    server=f"socks5://127.0.0.1:{local_port}",
                    meta={
                        "source": "clash",
                        "node": now_node,
                        "group": target_group.get("name", group_name),
                    },
                )
            except Exception as e:
                raise RuntimeError(f"Clash API 请求失败：{e}")


PROVIDER = ClashProvider()
