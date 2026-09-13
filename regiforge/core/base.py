from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

from .models import AccountResult, ExportResult, ProxyInfo, VerificationResult


LogFn = Callable[[str], None]


@dataclass
class RunContext:
    task_id: str
    index: int
    total: int
    captcha: "CaptchaProvider | None"
    email: "EmailProvider | None"
    proxy: "ProxyProvider"
    sms: "SmsProvider | None" = None
    config: dict[str, Any] = field(default_factory=dict)
    headless: bool = False
    logger: LogFn = print
    # Per-account state (NOT shared across concurrent accounts — concurrency safe)
    acquired_proxy: Any = None
    last_failure_class: str | None = None

    def log(self, msg: str) -> None:
        prefix = f"[{self.index}/{self.total}]"
        self.logger(f"{prefix} {msg}")


class CaptchaProvider(ABC):
    type: str = ""
    id: str = ""
    name: str = ""

    def configure(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}

    @abstractmethod
    async def solve(self, *, sitekey: str, page_url: str, **kwargs: Any) -> str | None:
        raise NotImplementedError

    def meta(self) -> dict[str, Any]:
        return {
            "id": f"{self.type}.{self.id}" if self.type else self.id,
            "type": self.type,
            "name": self.name,
            "provider_id": self.id,
        }


class EmailProvider(ABC):
    id: str = ""
    name: str = ""

    def configure(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}

    @abstractmethod
    def generate_address(self) -> str:
        raise NotImplementedError

    @abstractmethod
    async def wait_code(self, email: str, *, timeout: float = 120) -> str | None:
        raise NotImplementedError

    async def wait_link(self, email: str, *, timeout: float = 120) -> str | None:
        """获取验证链接（"点击邮件链接"验证模式）。

        默认实现返回 None；支持链接提取的 Provider 覆写此方法。
        """
        return None

    def meta(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name}


class SmsProvider(ABC):
    """短信接码 Provider：取号 → 收码 → 释放号码。

    对称于 EmailProvider，供需要手机号验证的注册项目使用。
    """

    id: str = ""
    name: str = ""

    def configure(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}

    @abstractmethod
    def get_phone(self) -> str:
        """获取一个手机号（同步，调用方用 asyncio.to_thread 包装）。"""
        raise NotImplementedError

    @abstractmethod
    async def get_verify_code(self, phone: str, *, timeout: float = 120) -> str | None:
        """轮询获取短信验证码，超时返回 None。"""
        raise NotImplementedError

    async def release_phone(self, phone: str) -> bool:
        """释放手机号（默认无操作，子类可覆写）。"""
        return True

    def meta(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name}


class ProxyProvider(ABC):
    id: str = ""
    name: str = ""

    def configure(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}

    @abstractmethod
    async def acquire(self) -> ProxyInfo | None:
        raise NotImplementedError

    async def release(self, proxy: ProxyInfo, failure_type: str | None = None) -> None:
        return None

    def meta(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name}


class VerificationProvider(ABC):
    id: str = ""
    name: str = ""

    def configure(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}

    @abstractmethod
    async def verify(self, account: AccountResult) -> VerificationResult:
        raise NotImplementedError

    def meta(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name}


class ExportProvider(ABC):
    id: str = ""
    name: str = ""

    def configure(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}

    @abstractmethod
    async def export(self, accounts: list[AccountResult]) -> ExportResult:
        raise NotImplementedError

    def meta(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name}


class RegistrationProject(ABC):
    id: str = ""
    name: str = ""
    required_captcha_types: list[str] = []
    description: str = ""

    @abstractmethod
    async def run_one(self, ctx: RunContext) -> AccountResult:
        raise NotImplementedError

    def meta(self) -> dict[str, Any]:
        from .project_ui import load_project_ui

        ui = load_project_ui(self.id)
        # schema 可覆盖/补充页面规划；代码声明仍为权威兜底
        required = list(ui.get("required_captcha_types") or self.required_captcha_types or [])
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description or ui.get("summary") or "",
            "required_captcha_types": required,
            "ui": ui,
        }
