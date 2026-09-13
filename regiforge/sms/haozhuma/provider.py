"""豪猪短信接码 Provider。配置键：sms.haozhuma。"""
from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from typing import Any

import requests

from core.base import SmsProvider

logger = logging.getLogger("sms.haozhuma")


class HaozhumaSmsProvider(SmsProvider):
    id = "haozhuma"
    name = "豪猪短信 (haozhuma.com)"

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}
        self._session: requests.Session | None = None
        self._token = ""
        self._token_lock = threading.Lock()

    def configure(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._session = None
        self._token = ""

    def _value(self, key: str, default: str = "") -> str:
        return str(self._config.get(key) or default).strip()

    def _base_url(self) -> str:
        return (self._value("base_url", "https://api.haozhuma.com")).rstrip("/")

    def _session_obj(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({"User-Agent": "RegiForge/1.0"})
        return self._session

    def _request(self, params: dict[str, Any]) -> dict[str, Any]:
        response = self._session_obj().get(
            f"{self._base_url()}/sms/", params=params, timeout=30
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError(f"豪猪返回格式错误: {data!r}")
        return data

    def _login(self) -> str:
        account = self._value("account")
        password = self._value("password")
        if not account or not password:
            raise RuntimeError("豪猪 API 账号或密码未设置")
        with self._token_lock:
            if self._token:
                return self._token
            data = self._request({"api": "login", "user": account, "pass": password})
            if str(data.get("code")) not in {"0", "200"} or not data.get("token"):
                raise RuntimeError(f"豪猪登录失败: {data.get('msg', data)}")
            self._token = str(data["token"])
            return self._token

    def _get_phone_sync(self) -> str:
        params: dict[str, Any] = {
            "api": "getPhone",
            "token": self._login(),
            "sid": self._value("sid"),
        }
        for key in ("isp", "Province", "ascription", "paragraph", "exclude", "uid", "author"):
            value = self._value(key)
            if value:
                params[key] = value
        if not params["sid"]:
            raise RuntimeError("豪猪短信项目 ID（sid）未设置")
        data = self._request(params)
        if str(data.get("code")) != "0" or not data.get("phone"):
            raise RuntimeError(f"豪猪取号失败: {data.get('msg', data)}")
        phone = str(data["phone"])
        logger.info("[豪猪取号] %s (%s %s)", phone, data.get("sp", ""), data.get("phone_gsd", ""))
        return phone

    def get_phone(self) -> str:
        return self._get_phone_sync()

    async def get_verify_code(self, phone: str, *, timeout: float = 120) -> str | None:
        return await asyncio.to_thread(self._get_verify_code_sync, phone, timeout)

    def _get_verify_code_sync(self, phone: str, timeout: float) -> str | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            data = self._request({
                "api": "getMessage",
                "token": self._login(),
                "sid": self._value("sid"),
                "phone": phone,
            })
            if str(data.get("code")) == "0":
                code = str(data.get("yzm") or "")
                match = re.search(r"\d{4,8}", code)
                if match:
                    code = match.group()
                if code:
                    logger.info("[豪猪验证码] %s", code)
                    return code
            time.sleep(min(15, max(1, deadline - time.monotonic())))
        return None

    async def release_phone(self, phone: str) -> bool:
        return await asyncio.to_thread(self._release_phone_sync, phone)

    def _release_phone_sync(self, phone: str) -> bool:
        if not phone:
            return False
        try:
            data = self._request({
                "api": "cancelRecv",
                "token": self._login(),
                "sid": self._value("sid"),
                "phone": phone,
            })
            ok = str(data.get("code")) in {"0", "200"}
            logger.info("[豪猪释放] %s -> %s", phone, "OK" if ok else data.get("msg", "失败"))
            return ok
        except Exception as exc:
            logger.error("[豪猪释放] %s 失败: %s", phone, exc)
            return False

    def meta(self) -> dict[str, Any]:
        base = super().meta()
        base["configured"] = bool(self._value("account") and self._value("password") and self._value("sid"))
        return base


PROVIDER = HaozhumaSmsProvider()
