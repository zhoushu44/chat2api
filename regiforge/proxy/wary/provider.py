"""Wary 粘性 WARP 代理池 Provider。

固定一个 API 地址动态获取代理：
- URL 含 {sid} 占位符时，每次 acquire 生成唯一粘性会话 ID，
  每账号固定独立出口（WARP 代理池），规避"身份到处飘"。
- 不含 {sid} 时按 API 默认轮换。
"""
from __future__ import annotations

import asyncio
import re
import uuid
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from core.base import ProxyProvider
from core.models import ProxyInfo


class WaryProxyProvider(ProxyProvider):
    """Wary 粘性 WARP 代理池 Provider（单一 API 地址）。"""

    id = "wary"
    name = "Wary 粘性代理池（API，单地址）"

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}

    def _headers(self) -> dict[str, str]:
        api_key = str(self._config.get("api_key") or "").strip()
        if not api_key:
            return {}
        if api_key.startswith("Bearer "):
            return {"Authorization": api_key}
        return {"X-API-Key": api_key}

    async def acquire(self) -> ProxyInfo | None:
        api_url = str(self._config.get("api_url") or "").strip()
        if not api_url:
            return None
        timeout = int(self._config.get("timeout") or 10)

        # WARP 粘性池：{sid} 每次生成唯一会话 ID，每账号固定独立出口
        sid: str | None = None
        if "{sid}" in api_url:
            sid = uuid.uuid4().hex[:12]
            api_url = api_url.replace("{sid}", sid)
            sid = parse_qs(urlparse(api_url).query).get("sid", [sid])[0]

        # 优先用 JSON 模式获取（拿到带认证的 proxy 字段，而非白名单端口）
        json_url = api_url
        if "type=txt" in json_url:
            json_url = json_url.replace("type=txt", "type=json")
        elif "type=" not in json_url:
            json_url += ("&" if "?" in json_url else "?") + "type=json"

        # 池可能暂时耗尽（高并发/多任务叠加），短重试等待实例回池
        max_retries = 3
        retry_delay = 2.0
        payload: dict[str, Any] | None = None
        for attempt in range(max_retries):
            async with httpx.AsyncClient(timeout=timeout, headers=self._headers()) as client:
                try:
                    resp = await client.get(json_url)
                    resp.raise_for_status()
                except Exception as e:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                        continue
                    raise RuntimeError(f"Wary 代理 API 请求失败：{e}")

            content_type = resp.headers.get("content-type", "").lower()
            if "application/json" in content_type or resp.text.strip().startswith("{"):
                payload = resp.json()
                code = payload.get("code")
                if code in (0, "00000", "0"):
                    break  # 成功
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                raise RuntimeError(f"Wary 代理池不可用：{payload.get('msg') or payload}")
            else:
                break  # 纯文本响应，直接解析

        proxy_str: str | None = None
        username: str | None = None
        password: str | None = None
        if payload is not None:
            proxies_list = (payload.get("data") or {}).get("proxies") or []
            if proxies_list:
                p = proxies_list[0]
                # proxy 字段是带认证端口（100xx），proxy_whitelist 是白名单端口（110xx）
                proxy_str = p.get("proxy") or p.get("proxy_whitelist") or ""
                username = p.get("username")
                password = p.get("password")
        else:
            proxy_str = self._extract_proxy(resp.text)

        if not proxy_str:
            raise RuntimeError("无法从 Wary API 响应中提取代理地址")

        proxy_info = self._normalize_proxy(proxy_str)
        if username or password:
            proxy_info = ProxyInfo(
                server=proxy_info.server,
                username=username or proxy_info.username,
                password=password or proxy_info.password,
                meta=proxy_info.meta,
            )
        if sid:
            meta = dict(proxy_info.meta or {})
            meta["sid"] = sid
            proxy_info = ProxyInfo(
                server=proxy_info.server,
                username=proxy_info.username,
                password=proxy_info.password,
                meta=meta,
            )
        return self._with_auth_forwarder(proxy_info)

    async def release(self, proxy: ProxyInfo, failure_type: str | None = None) -> None:
        # Stop forwarder if present (release listening socket + threads)
        forwarder = (proxy.meta or {}).get("forwarder")
        if forwarder:
            try:
                forwarder.stop()
            except Exception:
                pass

        sid = str((proxy.meta or {}).get("sid") or "").strip()
        api_url = str(self._config.get("api_url") or "").strip()
        if not sid or not api_url:
            return

        parsed = urlparse(api_url)
        release_url = f"{parsed.scheme}://{parsed.netloc}/api/pool/release"
        timeout = int(self._config.get("timeout") or 10)
        body: dict[str, Any] = {"session_id": sid}
        if failure_type:
            body["failure_type"] = failure_type
        async with httpx.AsyncClient(timeout=timeout, headers=self._headers()) as client:
            try:
                resp = await client.post(release_url, json=body)
                resp.raise_for_status()
            except Exception:
                pass  # best-effort 释放，不阻塞主流程

    async def report_failure(self, proxy: ProxyInfo, failure_type: str = "proxy_dead") -> None:
        """上报实例故障（不释放会话），触发服务端重启该实例数据通道。"""
        sid = str((proxy.meta or {}).get("sid") or "").strip()
        api_url = str(self._config.get("api_url") or "").strip()
        if not sid or not api_url:
            return
        parsed = urlparse(api_url)
        report_url = f"{parsed.scheme}://{parsed.netloc}/api/pool/report"
        timeout = int(self._config.get("timeout") or 10)
        async with httpx.AsyncClient(timeout=timeout, headers=self._headers()) as client:
            try:
                resp = await client.post(report_url, json={"session_id": sid, "failure_type": failure_type})
                resp.raise_for_status()
            except Exception:
                pass  # best-effort 上报，不阻塞主流程

    def _extract_proxy(self, content: str) -> str | None:
        text = content.strip()
        if not text:
            return None
        # 纯文本：一行 host 或 host:port 或 scheme://...，取第一行非空
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if lines:
            # 去掉首尾空白行外的杂质（如 html 表格第一格）
            first = lines[0]
            if first.endswith("</tr>") or "<tr" in first:
                m = re.search(r">([^<]+)</td>", first)
                if m:
                    return m.group(1).strip()
            return first
        return None

    def _normalize_proxy(self, proxy_str: str) -> ProxyInfo:
        proxy_str = proxy_str.strip()
        lower = proxy_str.lower()
        if not re.match(r"^(http|https|socks5|socks5h|socks4|socks4a)://", lower):
            proxy_str = f"socks5://{proxy_str}"

        parsed = urlparse(proxy_str)
        if not parsed.hostname or not parsed.port:
            raise ValueError(f"无效的代理格式：{proxy_str}（缺少主机或端口）")

        return ProxyInfo(
            server=proxy_str,
            username=unquote(parsed.username) if parsed.username else None,
            password=unquote(parsed.password) if parsed.password else None,
            meta={"source": "wary", "host": parsed.hostname, "port": parsed.port, "scheme": parsed.scheme},
        )

    def _with_auth_forwarder(self, proxy_info: ProxyInfo | None) -> ProxyInfo | None:
        if proxy_info is None:
            return None
        parsed = urlparse(proxy_info.server)
        username = proxy_info.username or parsed.username
        password = proxy_info.password or parsed.password
        if (not username and not password) or not parsed.hostname or not parsed.port:
            return proxy_info

        # 带认证：本地 HTTP 转发器（curl_cffi 不支持 SOCKS5 认证）
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
                meta={**proxy_info.meta, "upstream": proxy_info.server, "forwarder": forwarder},
            )
        except Exception as exc:
            raise RuntimeError(
                f"Forwarder 启动失败，curl_cffi 不支持 SOCKS5 认证无法回退: {exc}"
            ) from exc

    def meta(self) -> dict[str, Any]:
        base = super().meta()
        base["api_url"] = str(self._config.get("api_url") or "").strip()
        return base


PROVIDER = WaryProxyProvider()
