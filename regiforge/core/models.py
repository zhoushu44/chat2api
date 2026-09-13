from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class TaskConfig:
    project_id: str
    captcha_id: str
    email_id: str
    proxy_id: str
    sms_id: str = ""
    total: int = 1
    start: int = 1
    concurrency: int = 1
    stagger: int = 0
    headless: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskConfig":
        return cls(
            project_id=str(data.get("project_id") or ""),
            captcha_id=str(data.get("captcha_id") or ""),
            email_id=str(data.get("email_id") or ""),
            proxy_id=str(data.get("proxy_id") or "none"),
            sms_id=str(data.get("sms_id") or ""),
            total=int(data.get("total") or 1),
            start=int(data.get("start") or 1),
            concurrency=max(1, int(data.get("concurrency") or 1)),
            stagger=max(0, int(data.get("stagger") or 0)),
            headless=bool(data.get("headless") or False),
        )


@dataclass
class TaskStatus:
    task_id: str
    state: str = "pending"  # pending|running|stopping|stopped|done|failed
    done: int = 0
    ok: int = 0
    failed: int = 0
    total: int = 0
    message: str = ""
    project_id: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AccountResult:
    email: str = ""
    apikey: str | None = None
    status: str = "unknown"
    # 可观测字段：失败时定位卡在哪一步、为何失败、证据在哪
    failed_step: str = ""
    failure_class: str = ""
    error: str = ""
    evidence_dir: str = ""
    last_url: str = ""
    # 项目特有信息（如 tier/quota/plus_trial），由各项目注册成功时选择性填充
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.apikey)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VerificationResult:
    account_id: str = ""
    usable: bool = False
    status: str = "unknown"
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExportResult:
    exported: int = 0
    status: str = "unknown"
    detail: str = ""
    imported: int = 0
    consumed_credentials: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProxyInfo:
    """统一代理信息模型。

    server 字段支持的协议格式：
    - http://user:pass@host:port
    - https://user:pass@host:port
    - socks5://user:pass@host:port
    - socks5h://user:pass@host:port
    - socks4://host:port
    - socks4a://host:port
    - host:port（无协议，视上下文自动推断）
    """
    server: str
    username: str | None = None
    password: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def scheme(self) -> str:
        from urllib.parse import urlparse
        parsed = urlparse(self.server)
        return (parsed.scheme or "http").lower()

    @property
    def host(self) -> str:
        from urllib.parse import urlparse
        parsed = urlparse(self.server)
        if parsed.hostname:
            return parsed.hostname
        # 无协议前缀时，直接取 server
        if "://" not in self.server and ":" in self.server:
            return self.server.rsplit(":", 1)[0]
        return self.server

    @property
    def port(self) -> int | None:
        from urllib.parse import urlparse
        parsed = urlparse(self.server)
        if parsed.port:
            return parsed.port
        # 无协议前缀时尝试提取端口
        if "://" not in self.server and ":" in self.server:
            try:
                return int(self.server.rsplit(":", 1)[1])
            except (ValueError, IndexError):
                return None
        return None

    @staticmethod
    def parse(url: str) -> "ProxyInfo":
        """统一解析各种代理 URL 格式。

        支持：
        - http://user:pass@host:port
        - https://user:pass@host:port
        - socks5://user:pass@host:port
        - socks5h://user:pass@host:port
        - socks4://host:port
        - socks4a://host:port
        - host:port（自动添加 socks5:// 前缀）
        - user:pass@host:port（自动添加 socks5:// 前缀）
        """
        from urllib.parse import urlparse

        url = url.strip()
        if not url:
            raise ValueError("代理 URL 不能为空")

        if "://" in url:
            parsed = urlparse(url)
            return ProxyInfo(
                server=url,
                username=parsed.username,
                password=parsed.password,
                meta={"host": parsed.hostname, "port": parsed.port, "scheme": parsed.scheme},
            )

        # 无协议前缀：自动推断
        if "@" in url:
            # user:pass@host:port → socks5://
            server = f"socks5://{url}"
        elif ":" in url:
            # host:port → socks5://
            server = f"socks5://{url}"
        else:
            raise ValueError(f"无法解析代理地址：{url}")

        parsed = urlparse(server)
        return ProxyInfo(
            server=server,
            username=parsed.username,
            password=parsed.password,
            meta={"host": parsed.hostname, "port": parsed.port, "scheme": "socks5"},
        )

    def to_playwright(self) -> dict[str, str]:
        """转换为 Playwright 代理配置。
        
        注意：Playwright 的 Chromium 不支持 SOCKS5 认证。
        如果代理需要认证，返回不含认证的服务器地址，
        由浏览器启动时通过 --proxy-server 参数或系统代理处理。
        """
        from urllib.parse import urlparse
        
        parsed = urlparse(self.server)
        
        # 如果是 HTTP/HTTPS 代理，支持认证
        if parsed.scheme.lower() in ("http", "https"):
            data = {"server": self.server}
            if self.username:
                data["username"] = self.username
            if self.password:
                data["password"] = self.password
            return data
        
        # SOCKS5 代理：Playwright 不支持认证，返回不含认证的地址
        # 但如果用户名密码存在，说明需要认证，返回 None 让调用方处理
        if parsed.scheme.lower().startswith("socks"):
            if self.username or self.password:
                # 需要认证的 SOCKS5，Playwright 不支持
                # 返回基础地址，由上层通过其他方式处理
                host = parsed.hostname
                port = parsed.port
                return {"server": f"socks5://{host}:{port}"}
            else:
                # 免认证 SOCKS5，直接使用
                return {"server": self.server}
        
        # 其他协议，直接返回
        return {"server": self.server}
