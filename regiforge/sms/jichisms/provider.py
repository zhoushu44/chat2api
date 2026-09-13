"""疾驰短信接码 Provider — jichisms.com

移植自 https://github.com/Tumb1er1376/shangtang-register 的 SMSClient，
适配 RegiForge SmsProvider 基类。

配置键：sms.jichisms
  - token: 疾驰短信 fcToken（平台「我的Token」页面获取）
  - sid: 疾驰短信项目 ID（商汤科技对应项目）
  - ascription: 卡号类型（1=移动, 2=联通），默认 1
  - paragraph: 号段筛选（可选，如 138）
  - proxy: 可选代理地址（由 task_runner 自动注入）
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

import requests

from core.base import SmsProvider

logger = logging.getLogger("sms.jichisms")

JICHI_API = "https://www.jichisms.com"


class JichismsSmsProvider(SmsProvider):
    """疾驰短信接码：取号 → 轮询验证码 → 释放号码。"""

    id = "jichisms"
    name = "疾驰短信 (jichisms.com)"

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}
        self._session: requests.Session | None = None

    def configure(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._session = None

    # ---- 内部工具 ----

    def _token(self) -> str:
        return str(self._config.get("token") or "").strip()

    def _sid(self) -> str:
        return str(self._config.get("sid") or "").strip()

    def _ascription(self) -> str:
        return str(self._config.get("ascription") or "1")

    def _paragraph(self) -> str:
        return str(self._config.get("paragraph") or "").strip()

    def _proxies(self) -> dict[str, str] | None:
        proxy = str(self._config.get("proxy") or "").strip()
        if not proxy:
            return None
        return {"http": proxy, "https": proxy}

    def _session_obj(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            })
            token = self._token()
            if token:
                self._session.headers.update({"fcToken": token})
        return self._session

    def _ensure_token(self) -> None:
        if not self._token():
            raise RuntimeError("疾驰短信 fcToken 未设置，请到平台「我的Token」页面获取")

    def _post(self, path: str, data: dict, retries: int = 3) -> dict:
        url = (self._config.get("base_url") or JICHI_API).rstrip("/") + path
        last_exc: Exception | None = None
        for i in range(retries):
            try:
                r = self._session_obj().post(url, data=data, proxies=self._proxies(), timeout=30)
                return r.json()
            except Exception as e:
                last_exc = e
                logger.warning("[疾驰] 请求失败(第%d次): %s", i + 1, e)
                time.sleep(2 ** i)
        raise RuntimeError(f"疾驰请求失败: {last_exc}")

    # ---- SmsProvider 接口 ----

    def get_phone(self) -> str:
        """获取手机号（/api/user/getPhone）。"""
        self._ensure_token()
        data_payload: dict[str, Any] = {"project_id": self._sid()}
        if self._paragraph():
            data_payload["paragraph"] = self._paragraph()
        if self._ascription():
            data_payload["ascription"] = self._ascription()

        data = self._post("/api/user/getPhone", data_payload)
        if str(data.get("code")) != "1":
            raise RuntimeError(f"取号失败: {data.get('msg', data)}")
        d = data.get("data") or {}
        phone = d.get("phone") or data.get("phone")
        if not phone:
            raise RuntimeError(f"取号返回无 phone 字段: {data}")
        logger.info("[取号] %s (%s %s)", phone, d.get("sp", ""), d.get("phone_gsd", ""))
        return str(phone)

    async def get_verify_code(self, phone: str, *, timeout: float = 120) -> str | None:
        """轮询获取短信验证码（/api/user/getVerifyCode）。"""
        return await asyncio.to_thread(self._get_verify_code_sync, phone, timeout)

    def _get_verify_code_sync(self, phone: str, timeout: float) -> str | None:
        self._ensure_token()
        max_retries = int(timeout // 5) + 1
        interval = 5
        for i in range(max_retries):
            if i == 0:
                time.sleep(2)
            else:
                time.sleep(interval)
            try:
                data = self._post("/api/user/getVerifyCode", {
                    "project_id": self._sid(),
                    "phone": phone,
                }, retries=2)
                if str(data.get("code")) == "1":
                    code = str(data.get("msg", "")).strip()
                    m = re.search(r"\d{4,8}", code)
                    if m:
                        code = m.group()
                    logger.info("[验证码] 第%d次查询 -> %s", i + 1, code)
                    return code
                else:
                    msg = str(data.get("msg", ""))
                    if "频繁" in msg or "5秒" in msg:
                        logger.warning("[验证码] 频率限制，等待中 (%d/%d)", i + 1, max_retries)
                        continue
            except Exception as e:
                logger.warning("[验证码] 轮询失败: %s", e)
            logger.info("[验证码] 等待中 (%d/%d)", i + 1, max_retries)
        return None

    async def release_phone(self, phone: str) -> bool:
        """释放号码（/api/user/releasePhone）。"""
        return await asyncio.to_thread(self._release_phone_sync, phone)

    def _release_phone_sync(self, phone: str) -> bool:
        self._ensure_token()
        if not phone:
            return False
        try:
            data = self._post("/api/user/releasePhone", {
                "project_id": self._sid(),
                "phone": phone,
            })
            ok = str(data.get("code")) == "1"
            logger.info("[释放] %s -> %s", phone, "OK" if ok else data.get("msg", "?"))
            return ok
        except Exception as e:
            logger.error("[释放] %s 失败: %s", phone, e)
            return False

    def meta(self) -> dict[str, Any]:
        base = super().meta()
        base["configured"] = bool(self._token())
        return base


PROVIDER = JichismsSmsProvider()
