"""SOCKS5 代理 Provider - 支持单链接和 API 动态获取两种模式。"""
from __future__ import annotations

import json
import random
import re
from typing import Any
from urllib.parse import urlparse

import httpx
from core.base import ProxyProvider
from core.models import ProxyInfo


class Socks5Provider(ProxyProvider):
    """SOCKS5 代理 Provider。

    支持两种模式：
    1. 单链接模式：直接填写 socks5://host:port 链接（支持多行，自动轮换）
    2. API 动态模式：从 API 动态获取代理链接

    API 支持的返回格式：
    - 纯文本：host:port 或 socks5://host:port（每行一个）
    - JSON 对象：{"proxy": "host:port", "ip": "...", "port": ...}
    - JSON 数组：["host:port", ...] 或 [{"ip": "...", "port": ...}]
    - HTML 表格：<table><tr><td>host</td><td>port</td></tr></table>

    轮换机制：
    - _proxy_pool: 存储所有配置的代理地址
    - _proxy_index: 当前代理索引，每次 acquire() 递增
    - _failed_proxies: 失败代理集合，轮换时自动跳过
    - 成功时从 _failed_proxies 移除，失败时加入

    认证处理（2026-07-27 修复）：
    - 带认证的 socks5://user:pass@host:port 自动转换为本地 HTTP 转发器
    - 转发器失败时降级到 socks5h://user:pass@host:port（curl_cffi 原生支持）
    """

    id = "socks5"
    name = "SOCKS5 代理（多行轮换/API）"

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}
        self._forwarders: dict[str, Any] = {}
        self._proxy_pool: list[str] = []
        self._proxy_index: int = 0
        self._failed_proxies: set[str] = set()

    async def acquire(self) -> ProxyInfo | None:
        """获取代理。
        
        支持三种模式：
        1. API 动态模式：从 API 动态获取代理列表
        2. 多行轮换模式：手动配置多个代理地址，自动轮换
        3. 直连模式：留空时直连
        
        支持 socks5:// 和 socks5h:// 协议前缀。
        """
        api_url = str(self._config.get("api_url") or "").strip()
        if api_url:
            return await self._acquire_from_api()
        
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
            return self._with_auth_forwarder(proxy_info)
        
        return None

    def _with_auth_forwarder(self, proxy_info: ProxyInfo | None) -> ProxyInfo | None:
        if proxy_info is None:
            return None
        parsed = urlparse(proxy_info.server)
        # 用 proxy_info 上已 unquote 的 username/password（_normalize_proxy 已解码）
        username = proxy_info.username or parsed.username
        password = proxy_info.password or parsed.password
        if not username and not password:
            return proxy_info
        if not parsed.hostname or not parsed.port:
            raise ValueError("SOCKS5 代理缺少主机或端口")

        cached = self._forwarders.get(proxy_info.server)
        if cached is not None:
            return ProxyInfo(server=cached[1], meta=proxy_info.meta)

        try:
            from .http_forwarder import Socks5HttpForwarder

            forwarder = Socks5HttpForwarder(
                remote_host=parsed.hostname,
                remote_port=parsed.port,
                username=username or "",
                password=password or "",
            )
            local_server = forwarder.start_sync()
            self._forwarders[proxy_info.server] = (forwarder, local_server)
            return ProxyInfo(
                server=local_server,
                meta={**proxy_info.meta, "upstream": proxy_info.server},
            )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "SOCKS5 本地转发器创建失败 (%s)，回退到 socks5h://", exc
            )
            # 构建 socks5h:// 带认证 URL（curl_cffi 支持此格式）
            from urllib.parse import unquote
            u = username or ""
            p = password or ""
            netloc = f"{u}:{p}@{parsed.hostname}:{parsed.port}"
            fallback = f"socks5h://{netloc}"
            return ProxyInfo(
                server=fallback,
                username=u,
                password=p,
                meta={**proxy_info.meta, "forwarder_fallback": str(exc)},
            )

    async def _acquire_from_api(self) -> ProxyInfo | None:
        """从 API 动态获取代理。"""
        api_url = str(self._config.get("api_url") or "").strip()
        if not api_url:
            return None
        api_key = str(self._config.get("api_key") or "").strip()
        timeout = int(self._config.get("timeout") or 10)
        protocol = str(self._config.get("protocol") or "socks5").lower()
        if protocol not in {"socks5", "socks5h"}:
            protocol = "socks5"

        # WARP 等粘性代理池：URL 含 {sid} 占位符时，每次 acquire 生成唯一
        # 粘性会话 ID（每账号独立固定出口，规避"身份到处飘"）；不写则按 API 默认轮换。
        sid: str | None = None
        if "{sid}" in api_url:
            import uuid
            sid = uuid.uuid4().hex[:12]
            api_url = api_url.replace("{sid}", sid)

        headers = {}
        if api_key:
            if api_key.startswith("Bearer "):
                headers["Authorization"] = api_key
            else:
                headers["X-API-Key"] = api_key

        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            try:
                resp = await client.get(api_url)
                resp.raise_for_status()
            except Exception as e:
                raise RuntimeError(f"代理 API 请求失败：{e}")

        content = resp.text.strip()
        if not content:
            return None

        # 尝试解析并提取代理
        proxy_str = None
        try:
            data = json.loads(content)
            proxy_str = self._extract_from_json(data)
        except json.JSONDecodeError:
            if "<table" in content.lower() and "<tr" in content.lower():
                proxy_str = self._extract_from_html(content)
            else:
                proxy_str = self._extract_from_text(content)

        if not proxy_str:
            raise RuntimeError("无法从 API 响应中提取代理地址")

        proxy_info = self._normalize_proxy(proxy_str)
        if sid:
            meta = dict(proxy_info.meta or {})
            meta["sid"] = sid
            proxy_info = ProxyInfo(
                server=proxy_info.server,
                username=proxy_info.username,
                password=proxy_info.password,
                meta=meta,
            )
        # API 返回的代理也可能是带认证的，需要转发器
        return self._with_auth_forwarder(proxy_info)

    def _extract_from_json(self, data: Any) -> str | None:
        """从 JSON 响应中提取代理地址。"""
        json_path = str(self._config.get("json_path") or "").strip()

        # 1. 优先使用 json_path 提取
        if json_path:
            try:
                result = data
                for key in json_path.split("."):
                    if isinstance(result, dict):
                        result = result[key]
                    elif isinstance(result, list):
                        result = result[int(key)]
                    else:
                        break
                if isinstance(result, str):
                    return result
            except (KeyError, IndexError, ValueError, TypeError):
                pass

        # 2. 自动探测常见字段名
        if isinstance(data, dict):
            for key in ["proxy", "proxies", "ip", "host", "address", "data", "result"]:
                if key in data:
                    value = data[key]
                    if isinstance(value, str):
                        return value
                    elif isinstance(value, dict):
                        nested = self._extract_from_json(value)
                        if nested:
                            return nested
                    elif isinstance(value, list) and value:
                        first = value[0]
                        if isinstance(first, str):
                            return first
                        elif isinstance(first, dict):
                            nested = self._extract_from_json(first)
                            if nested:
                                return nested

            # 3. 尝试提取 ip + port 组合
            ip = None
            port = None
            for key in ["ip", "host", "server", "addr"]:
                if key in data and isinstance(data[key], str):
                    ip = data[key]
                    break
            for key in ["port", "PORT"]:
                if key in data:
                    port = str(data[key])
                    break
            if ip and port:
                return f"{ip}:{port}"

        # 4. JSON 数组
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, str):
                return first
            elif isinstance(first, dict):
                return self._extract_from_json(first)

        return None

    def _extract_from_text(self, content: str) -> str | None:
        """从纯文本响应中提取代理地址。"""
        lines = [line.strip() for line in content.split("\n") if line.strip()]
        if not lines:
            return None

        proxy_lines = []
        for line in lines:
            if line.startswith("#"):
                continue
            if re.match(r"^[\w\.\-]+:\d+$", line):
                proxy_lines.append(line)
            elif line.startswith("socks5://") or line.startswith("socks5h://"):
                proxy_lines.append(line)

        if not proxy_lines:
            match = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d{2,5})", content)
            if match:
                return match.group(1)
            return None

        return random.choice(proxy_lines)

    def _extract_from_html(self, html: str) -> str | None:
        """从 HTML 表格中提取代理地址。"""
        pattern = r"<tr[^>]*>.*?<td[^>]*>([\w\.\-]+)</td>.*?<td[^>]*>(\d{2,5})</td>.*?</tr>"
        matches = re.findall(pattern, html, re.IGNORECASE | re.DOTALL)
        if not matches:
            pattern = r"<td[^>]*>([\w\.\-]+)</td>.*?<td[^>]*>(\d{2,5})</td>"
            matches = re.findall(pattern, html, re.IGNORECASE | re.DOTALL)

        if not matches:
            return None

        ip, port = random.choice(matches)
        return f"{ip}:{port}"

    def _normalize_proxy(self, proxy_str: str) -> ProxyInfo:
        """标准化代理地址为 ProxyInfo。"""
        from urllib.parse import unquote

        proxy_str = proxy_str.strip()

        if "://" in proxy_str:
            parsed = urlparse(proxy_str)
            return ProxyInfo(
                server=proxy_str,
                username=unquote(parsed.username) if parsed.username else None,
                password=unquote(parsed.password) if parsed.password else None,
                meta={"source": "socks5", "host": parsed.hostname, "port": parsed.port},
            )

        # 没有协议前缀，添加
        if "@" in proxy_str:
            auth, rest = proxy_str.rsplit("@", 1)
            host, port = rest.rsplit(":", 1)
            username, password = auth.split(":", 1) if ":" in auth else (None, None)
            server = f"socks5://{username}:{password}@{host}:{port}" if username else f"socks5://{host}:{port}"
        else:
            if ":" not in proxy_str:
                raise ValueError(f"无效的代理格式：{proxy_str}")
            host, port = proxy_str.rsplit(":", 1)
            server = f"socks5://{host}:{port}"

        parsed = urlparse(server)
        return ProxyInfo(
            server=server,
            username=unquote(parsed.username) if parsed.username else None,
            password=unquote(parsed.password) if parsed.password else None,
            meta={"source": "socks5", "host": parsed.hostname, "port": parsed.port},
        )


PROVIDER = Socks5Provider()
