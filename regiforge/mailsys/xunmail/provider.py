from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests

from core.base import EmailProvider


DEFAULT_API_ADDRESS = "https://www.xunmail.cn/api-doc"


@dataclass
class OutlookAccount:
    email: str
    client_id: str
    refresh_token: str
    started_at: float = 0.0


def parse_account_line(raw: str) -> OutlookAccount | None:
    text = str(raw or "").strip()
    if not text or text.startswith("#"):
        return None
    parts = text.split("----")
    email = str(parts[0] or "").strip()
    client_id = str(parts[2] if len(parts) > 2 else "").strip()
    refresh_token = str(parts[3] if len(parts) > 3 else "").replace("$", "").strip()
    if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email):
        return None
    if not client_id or not refresh_token:
        return None
    return OutlookAccount(email=email, client_id=client_id, refresh_token=refresh_token)


def normalize_api_base(value: str = DEFAULT_API_ADDRESS) -> str:
    raw = str(value or DEFAULT_API_ADDRESS).strip() or DEFAULT_API_ADDRESS
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("寻邮 API 地址只支持 HTTP 或 HTTPS")
    path = parsed.path or ""
    path = re.sub(
        r"/(?:api-doc|api/(?:graph|oauth2)/mail-(?:all|latest|count|by-index))/?$",
        "",
        path,
        flags=re.IGNORECASE,
    ).rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}{path}" if path else f"{parsed.scheme}://{parsed.netloc}"


def build_endpoints(api_address: str) -> dict[str, str]:
    base = normalize_api_base(api_address)
    return {
        "graph": f"{base}/api/graph/mail-all",
        "oauth2": f"{base}/api/oauth2/mail-all",
    }


def normalize_code_text(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"[０-９]", lambda m: chr(ord(m.group(0)) - 0xFEE0), text)
    return re.sub(r"[\u200b-\u200f\u202a-\u202e]", "", text)


def extract_verification_code(value: str) -> str:
    text = normalize_code_text(value)
    candidates: list[tuple[str, int]] = []

    def add(raw: str, score: int = 0) -> None:
        code = re.sub(r"[^\d]", "", str(raw or ""))
        if len(code) < 4 or len(code) > 8 or re.match(r"^(19|20)\d{2}$", code):
            return
        candidates.append((code, score + (4 if len(code) == 6 else 0)))

    for match in re.finditer(
        r"(验证码|校验码|动态码|安全码|code|passcode|otp|verification)[^\d]{0,40}((?:\d[\s-]*){4,8})",
        text,
        flags=re.IGNORECASE,
    ):
        add(match.group(2), 10)
    for match in re.finditer(r"(?:^|[^\d])((?:\d[\s-]*){4,8})(?!\d)", text):
        add(match.group(1), 1)
    candidates.sort(key=lambda item: (item[1], len(item[0])), reverse=True)
    return candidates[0][0] if candidates else ""


def parse_mail_time(value: Any) -> float:
    if isinstance(value, (int, float)) and value:
        number = float(value)
        if number > 1e12:
            return number
        if number > 1e9:
            return number * 1000
    raw = str(value or "").strip()
    if not raw:
        return 0.0
    if re.fullmatch(r"\d{10,13}", raw):
        return parse_mail_time(float(raw))
    try:
        from email.utils import parsedate_to_datetime

        return parsedate_to_datetime(raw).timestamp() * 1000
    except Exception:
        pass
    try:
        import datetime as dt

        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp() * 1000
    except Exception:
        return 0.0


def extract_code_from_mail(mail: dict[str, Any]) -> str:
    direct = re.sub(
        r"[^\d]",
        "",
        str(mail.get("verification_code") or mail.get("code") or mail.get("otp") or ""),
    )
    if 4 <= len(direct) <= 8:
        return direct
    return extract_verification_code(
        "\n".join(
            str(mail.get(key) or "")
            for key in ("subject", "bodyPreview", "content", "fullContent", "body", "text")
        )
    )


def mail_time(mail: dict[str, Any]) -> float:
    return parse_mail_time(
        mail.get("receivedDateTime")
        or mail.get("received_at")
        or mail.get("date")
        or mail.get("time")
        or mail.get("timestamp")
    )


def mail_list(body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        return []
    if isinstance(body.get("mails"), list):
        return [item for item in body["mails"] if isinstance(item, dict)]
    data = body.get("data")
    if isinstance(data, dict) and isinstance(data.get("mails"), list):
        return [item for item in data["mails"] if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def select_latest_verification(
    mailbox_responses: list[dict[str, Any]],
    not_before: float = 0.0,
) -> dict[str, Any] | None:
    minimum_time = float(not_before or 0.0) - 120_000
    items: list[dict[str, Any]] = []
    for response in mailbox_responses:
        mailbox = str(response.get("mailbox") or "")
        for order, mail in enumerate(mail_list(response.get("data"))):
            code = extract_code_from_mail(mail)
            if not code:
                continue
            stamp = mail_time(mail)
            if stamp and minimum_time and stamp < minimum_time:
                continue
            items.append(
                {
                    "mailbox": mailbox,
                    "mail": mail,
                    "order": order,
                    "time": stamp,
                    "code": code,
                }
            )
    items.sort(
        key=lambda item: (
            0 if item["time"] else 1,
            -(item["time"] or 0),
            item["order"],
        )
    )
    return items[0] if items else None


class XunmailEmailProvider(EmailProvider):
    """Outlook 四段式 + 寻邮 Graph/OAuth2 取码。

    账号串格式：
      email----password----client_id----refresh_token
    密码段仅兼容格式，不会发送。
    """

    id = "xunmail"
    name = "寻邮 Outlook"

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}
        self._queue: list[OutlookAccount] = []
        self._active: dict[str, OutlookAccount] = {}
        self._lock = asyncio.Lock()

    def configure(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._queue = self._parse_accounts(self._config.get("accounts"))
        self._active = {}

    def _parse_accounts(self, raw: Any) -> list[OutlookAccount]:
        if isinstance(raw, list):
            lines = [str(item) for item in raw]
        else:
            lines = str(raw or "").splitlines()
        accounts: list[OutlookAccount] = []
        seen: set[str] = set()
        for line in lines:
            account = parse_account_line(line)
            if not account:
                continue
            key = account.email.lower()
            if key in seen:
                continue
            seen.add(key)
            accounts.append(account)
        return accounts

    def _api_address(self) -> str:
        return str(self._config.get("api_address") or DEFAULT_API_ADDRESS).strip() or DEFAULT_API_ADDRESS

    def generate_address(self) -> str:
        if not self._queue:
            raise RuntimeError(
                "寻邮账号池为空；请在 email.xunmail.accounts 中配置 Outlook 四段式账号串"
            )
        account = self._queue.pop(0)
        account.started_at = time.time() * 1000
        self._active[account.email.lower()] = account
        return account.email

    def _lookup(self, email: str) -> OutlookAccount:
        key = str(email or "").strip().lower()
        account = self._active.get(key)
        if account:
            return account
        for item in self._queue:
            if item.email.lower() == key:
                item.started_at = item.started_at or (time.time() * 1000)
                self._active[key] = item
                return item
        raise RuntimeError(f"未找到邮箱凭据: {email}")

    def _fetch_mailbox(
        self,
        endpoint: str,
        account: OutlookAccount,
        mailbox: str,
    ) -> dict[str, Any]:
        response = requests.post(
            endpoint,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            json={
                "email": account.email,
                "client_id": account.client_id,
                "refresh_token": account.refresh_token,
                "mailbox": mailbox,
            },
            timeout=30,
        )
        try:
            data = response.json()
        except Exception:
            data = {}
        if not response.ok:
            message = (
                data.get("error")
                or data.get("message")
                or data.get("detail")
                or (data.get("data") or {}).get("error")
                or f"寻邮接口失败（HTTP {response.status_code}）"
            )
            raise RuntimeError(str(message))
        return {"mailbox": mailbox, "data": data}

    def _fetch_both_folders(self, endpoint: str, account: OutlookAccount) -> list[dict[str, Any]]:
        successful: list[dict[str, Any]] = []
        errors: list[str] = []
        for mailbox in ("INBOX", "Junk"):
            try:
                successful.append(self._fetch_mailbox(endpoint, account, mailbox))
            except Exception as exc:
                errors.append(f"{mailbox}: {exc}")
        if not successful:
            raise RuntimeError("; ".join(errors) or "寻邮接口请求失败")
        return successful

    def _fetch_code_once(self, account: OutlookAccount) -> str:
        endpoints = build_endpoints(self._api_address())
        mode_errors: list[str] = []
        for mode in ("graph", "oauth2"):
            try:
                responses = self._fetch_both_folders(endpoints[mode], account)
            except Exception as exc:
                mode_errors.append(f"{mode}: {exc}")
                continue
            latest = select_latest_verification(responses, account.started_at)
            if latest and latest.get("code"):
                return str(latest["code"])
        if mode_errors:
            # 接口可用但暂无新验证码时，返回空继续轮询
            if all("HTTP" not in err and "失败" not in err for err in mode_errors):
                return ""
        return ""

    def _wait_code_sync(self, email: str, timeout: float, interval: float = 2.5) -> str | None:
        account = self._lookup(email)
        if not account.started_at:
            account.started_at = time.time() * 1000
        deadline = time.time() + timeout
        last_error = ""
        while time.time() < deadline:
            try:
                code = self._fetch_code_once(account)
                if code:
                    return code
            except Exception as exc:
                last_error = str(exc)
            time.sleep(interval)
        if last_error:
            raise RuntimeError(f"等待验证码超时，最后错误: {last_error}")
        return None

    async def wait_code(self, email: str, *, timeout: float = 120) -> str | None:
        # 不加全局锁：to_thread 已隔离阻塞 sleep，不同邮箱 key 互不冲突。
        # 加锁会导致 concurrency=N 时 N 个账号串行等码，退化为假并发。
        return await asyncio.to_thread(self._wait_code_sync, email, timeout)


PROVIDER = XunmailEmailProvider()
