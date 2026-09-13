from __future__ import annotations

import asyncio
import re
import time
from typing import Any
from urllib.parse import unquote, urlparse

import requests
import urllib3

from core.base import EmailProvider

# 允许通过代理（如 Clash）连接时跳过 SSL 验证
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


DEFAULT_BASE_URL = "https://mailnest.top"
SUCCESS_CODE = "00000"

# 注册项目 → MailNest 临时邮箱 product_code（/api/product/info）
# 不同站点过滤规则不同，不能共用 chatgpt001
DEFAULT_PROJECT_CODES: dict[str, str] = {
    "chatgpt_register": "chatgpt001",
    "nvidia_build": "nvidia001",
    "grok_register": "x-ai001",
    "zcode_register": "z-ai001",
    "outlook_register": "microsoft001",
}


def normalize_base_url(value: str = DEFAULT_BASE_URL) -> str:
    raw = str(value or DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
    return raw.rstrip("/")


def extract_code_fallback(value: str) -> str:
    text = re.sub(r"[\u200b-\u200f\u202a-\u202e]", "", str(value or ""))
    text = re.sub(r"[０-９]", lambda m: chr(ord(m.group(0)) - 0xFEE0), text)
    candidates: list[tuple[str, int]] = []

    def add(raw: str, score: int = 0) -> None:
        code = re.sub(r"[^\d]", "", str(raw or ""))
        if len(code) < 4 or len(code) > 8 or re.match(r"^(19|20)\d{2}$", code):
            return
        candidates.append((code, score + (4 if len(code) == 6 else 0)))

    def add_alnum(raw: str, score: int = 0) -> None:
        """添加字母数字混合验证码（如 FPW-62T、ABC123）。"""
        code = re.sub(r"\s+", "", str(raw or ""))
        if not code or len(code) < 4 or len(code) > 10:
            return
        candidates.append((code, score))

    # 1. 纯数字验证码：关键词附近
    for match in re.finditer(
        r"(验证码|校验码|动态码|安全码|code|passcode|otp|verification)[^\d]{0,40}((?:\d[\s-]*){4,8})",
        text,
        flags=re.IGNORECASE,
    ):
        add(match.group(2), 10)

    # 2. 字母数字混合验证码：关键词附近（如 FPW-62T、X4K9P2）
    for match in re.finditer(
        r"(?:code|passcode|otp|verification|验证码|校验码)[^\w]{0,20}([A-Z0-9]{3,8}-?[A-Z0-9]{0,8})",
        text,
        flags=re.IGNORECASE,
    ):
        add_alnum(match.group(1), 12)

    # 3. 字母数字混合验证码：独立行（如邮件正文中单独一行的 FPW-62T）
    for match in re.finditer(r"(?:^|\n)\s*([A-Z0-9]{2,4}-[A-Z0-9]{2,4})\s*(?:\n|$)", text):
        add_alnum(match.group(1), 8)
    for match in re.finditer(r"(?:^|\n)\s*([A-Z]{2,4}\d{2,4})\s*(?:\n|$)", text):
        add_alnum(match.group(1), 6)

    # 4. 纯数字验证码：任意位置
    for match in re.finditer(r"(?:^|[^\d])((?:\d[\s-]*){4,8})(?!\d)", text):
        add(match.group(1), 1)

    candidates.sort(key=lambda item: (item[1], len(item[0])), reverse=True)
    return candidates[0][0] if candidates else ""


def pick_code_from_mail(mail: dict[str, Any]) -> str:
    # code_match 字段可能由 MailNest 预提取，若含字母数字则直接用
    cm = str(mail.get("code_match") or "").strip()
    if cm and 3 <= len(cm) <= 12 and re.search(r"[A-Za-z]", cm):
        return cm
    # MailNest 的 code 字段不可靠（可能返回假值如 333333），跳过
    combined = "\n".join(
        str(mail.get(key) or "")
        for key in ("subject", "body_preview", "body", "text", "content")
    )
    return extract_code_fallback(combined)


class MailnestEmailProvider(EmailProvider):
    """MailNest 临时邮箱：按 project_code 购买，轮询 receive 取验证码。

    配置键：email.mailnest
      - api_key: Bearer API Key
      - base_url: 默认 https://mailnest.top
      - project_code: 默认/兜底编码（如 chatgpt001）；可被 project_codes 覆盖
      - project_codes: 按注册项目映射，如 {"nvidia_build": "nvidia001"}
      - registration_project_id: 运行时注入（task_runner），用于解析映射
      - poll_interval: 轮询间隔秒，默认 3
      - auto_release: 取码超时后是否自动释放（退款冻结），默认 true
    """

    id = "mailnest"
    name = "MailNest 临时邮箱"

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}
        self._active: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    def configure(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._active = {}

    def _base_url(self) -> str:
        return normalize_base_url(str(self._config.get("base_url") or DEFAULT_BASE_URL))

    def _api_key(self) -> str:
        return str(self._config.get("api_key") or "").strip()

    def _registration_project_id(self) -> str:
        return str(
            self._config.get("registration_project_id")
            or self._config.get("project_id")
            or ""
        ).strip()

    def _project_codes_map(self) -> dict[str, str]:
        merged = dict(DEFAULT_PROJECT_CODES)
        raw = self._config.get("project_codes")
        if isinstance(raw, str):
            text = raw.strip()
            if text:
                try:
                    import json

                    parsed = json.loads(text)
                    raw = parsed if isinstance(parsed, dict) else {}
                except Exception:
                    raw = {}
            else:
                raw = {}
        if isinstance(raw, dict):
            for key, value in raw.items():
                code = str(value or "").strip()
                pid = str(key or "").strip()
                if pid and code:
                    merged[pid] = code
        return merged

    def _project_code(self) -> str:
        """解析购买用 project_code：映射 > 显式 project_code > 默认映射。"""
        reg_id = self._registration_project_id()
        codes = self._project_codes_map()
        if reg_id and codes.get(reg_id):
            return codes[reg_id]
        explicit = str(self._config.get("project_code") or "").strip()
        if explicit:
            return explicit
        if reg_id and DEFAULT_PROJECT_CODES.get(reg_id):
            return DEFAULT_PROJECT_CODES[reg_id]
        return ""

    def _poll_interval(self) -> float:
        try:
            return max(1.0, float(self._config.get("poll_interval") or 3))
        except (TypeError, ValueError):
            return 3.0

    def _auto_release(self) -> bool:
        value = self._config.get("auto_release")
        if value is None:
            return True
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() not in {"0", "false", "no", "off"}

    def _proxies(self) -> dict[str, str] | None:
        """可选 HTTP/SOCKS 代理：通过代理连接 MailNest API。
        
        支持多行代理配置，自动选择第一个可用代理。
        带认证的 SOCKS5 代理会自动转换为本地 HTTP 转发器。
        """
        proxy_config = str(self._config.get("proxy") or "").strip()
        if not proxy_config:
            return None
        
        # 处理多行代理配置，取第一个代理
        proxy_lines = [line.strip() for line in proxy_config.split("\n") if line.strip()]
        if not proxy_lines:
            return None
        
        # 使用第一个代理，并尝试转换带认证的 SOCKS5
        proxy = proxy_lines[0]
        proxy = self._convert_socks5_proxy(proxy)
        return {"http": proxy, "https": proxy}
    
    def _convert_socks5_proxy(self, proxy: str) -> str:
        """将带认证的 SOCKS5 代理转换为本地 HTTP 转发器。
        
        复用 Socks5Provider 的 _with_auth_forwarder 逻辑。
        如果转换失败，回退到 socks5h:// 格式。
        """
        if not proxy or "://" not in proxy:
            return proxy
        
        parsed = urlparse(proxy)

        # 只有带认证的 socks5:// 才需要转换
        if not parsed.scheme.lower().startswith("socks"):
            return proxy  # http:// 或其他，直接返回
        if not parsed.username and not parsed.password:
            return proxy  # 免认证 socks5，直接返回

        try:
            # 尝试创建本地 HTTP 转发器
            from proxy.socks5.http_forwarder import Socks5HttpForwarder
            forwarder = Socks5HttpForwarder(
                remote_host=parsed.hostname,
                remote_port=parsed.port,
                username=unquote(parsed.username or ""),
                password=unquote(parsed.password or ""),
            )
            local_server = forwarder.start_sync()
            return local_server  # http://127.0.0.1:xxxx
        except Exception:
            # 转发器创建失败，降级到 socks5h://
            import logging
            logging.getLogger(__name__).warning(
                "MailNest SOCKS5 转发器创建失败，降级到 socks5h://"
            )
            netloc = f"{parsed.username}:{parsed.password}@{parsed.hostname}:{parsed.port}"
            return f"socks5h://{netloc}"

    def _headers(self) -> dict[str, str]:
        key = self._api_key()
        if not key:
            raise RuntimeError("MailNest 未配置 api_key；请在 email.mailnest.api_key 或 .env MAILNEST_API_KEY 中填写")
        return {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        auth: bool = True,
        timeout: float = 60,
        retries: int = 5,
    ) -> Any:
        url = f"{self._base_url()}{path}"
        headers = self._headers() if auth else {"Accept": "application/json"}
        proxies = self._proxies()
        last_error: Exception | None = None
        for attempt in range(1, max(1, retries) + 1):
            try:
                with requests.Session() as session:
                    if proxies is None:
                        session.trust_env = False
                    response = session.request(
                        method,
                        url,
                        headers=headers,
                        json=json_body,
                        params=params,
                        timeout=timeout,
                        proxies=proxies,
                        verify=False,
                    )
            except (
                requests.exceptions.SSLError,
                requests.exceptions.ConnectionError,
                requests.exceptions.ReadTimeout,
                requests.exceptions.Timeout,
            ) as exc:
                last_error = exc
                if attempt >= retries:
                    break
                # 指数退避：第 1 次等 2s，第 2 次等 4s，第 3 次等 6s（上限 10s）
                time.sleep(min(2.0 * attempt, 10.0))
                continue
            if response.status_code == 401:
                raise RuntimeError("MailNest API Key 无效或已失效（HTTP 401）")
            try:
                payload = response.json()
            except Exception as exc:
                raise RuntimeError(
                    f"MailNest 响应非 JSON（HTTP {response.status_code}）: {response.text[:200]}"
                ) from exc
            if not response.ok:
                detail = payload.get("detail") or payload.get("msg") or payload
                raise RuntimeError(f"MailNest HTTP {response.status_code}: {detail}")
            if isinstance(payload, dict) and "code" in payload:
                code = str(payload.get("code") or "")
                if code != SUCCESS_CODE:
                    msg = payload.get("msg") or code
                    raise RuntimeError(f"MailNest 业务错误 {code}: {msg}")
                return payload.get("data")
            return payload
        raise RuntimeError(f"MailNest 网络请求失败（已重试 {retries} 次）: {last_error}")

    def get_balance(self) -> dict[str, Any]:
        data = self._request("GET", "/api/v1/balance")
        return data if isinstance(data, dict) else {}

    def get_product_info(self) -> dict[str, Any]:
        data = self._request("GET", "/api/product/info", auth=False)
        return data if isinstance(data, dict) else {}

    def _buy_temporary(self, project_code: str, count: int = 1) -> dict[str, Any]:
        data = self._request(
            "POST",
            "/api/v1/email/temporary/buy",
            json_body={"project_code": project_code, "count": count},
        )
        if isinstance(data, list) and data:
            item = data[0]
            if isinstance(item, dict) and item.get("email"):
                return item
        raise RuntimeError(f"MailNest 购买临时邮箱返回异常: {data!r}")

    def _receive_once(self, email: str) -> list[dict[str, Any]]:
        try:
            data = self._request(
                "POST",
                "/api/v1/email/receive",
                json_body={"email": email},
            )
        except RuntimeError as exc:
            text = str(exc)
            # D0005 取件失败请稍后再试 / 暂无邮件：继续轮询
            if "D0005" in text or "取件失败" in text:
                return []
            raise
        except (requests.exceptions.ReadTimeout, requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            # 网络超时/连接错误：交由上层 _wait_code_sync 的 transient_streak 计数
            return []
        if data is None:
            return []
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            return [data]
        return []

    def release_email(self, email: str) -> None:
        address = str(email or "").strip()
        if not address:
            return
        try:
            self._request(
                "POST",
                "/api/v1/email/release",
                json_body={"email": address},
            )
        except RuntimeError as exc:
            # 已扣费/不可释放时忽略，避免影响主流程
            if "D0004" in str(exc):
                return
            raise
        finally:
            self._active.pop(address.lower(), None)

    def generate_address(self) -> str:
        project_code = self._project_code()
        if not project_code:
            reg = self._registration_project_id() or "(未指定注册项目)"
            raise RuntimeError(
                "MailNest 未解析到 project_code；"
                f"请配置 email.mailnest.project_codes['{reg}'] 或 project_code "
                f"（已知默认: {DEFAULT_PROJECT_CODES}）"
            )
        item = self._buy_temporary(project_code, count=1)
        email = str(item.get("email") or "").strip()
        if not email:
            raise RuntimeError(f"MailNest 购买成功但未返回邮箱: {item!r}")
        self._active[email.lower()] = {
            "email": email,
            "order_id": item.get("id"),
            "project_code": item.get("project_code") or project_code,
            "registration_project_id": self._registration_project_id(),
            "started_at": time.time(),
            "raw": item,
        }
        return email

    def _wait_code_sync(self, email: str, timeout: float, skip_codes=None) -> str | None:
        address = str(email or "").strip()
        if not address:
            raise RuntimeError("等待验证码时邮箱地址为空")
        skip = {str(c).strip() for c in (skip_codes or ()) if c}
        deadline = time.time() + timeout
        interval = self._poll_interval()
        # 只记真正的业务错误；网络抖动（ReadTimeout/ConnectionError）频繁出现，
        # 不应被当作"最后错误"导致超时后释放邮箱。
        last_error = ""
        transient_streak = 0
        while time.time() < deadline:
            try:
                mails = self._receive_once(address)
                transient_streak = 0
                for mail in mails:
                    code = pick_code_from_mail(mail)
                    # skip_codes：过滤已见过的旧码（如密码注册切流程后旧 OTP 失效），
                    # 服务端邮件列表不变，仅靠本地 pop 无法排除旧邮件
                    if code and str(code).strip() not in skip:
                        self._active.pop(address.lower(), None)
                        return code
            except requests.exceptions.ReadTimeout:
                transient_streak += 1
                # 连续多次 read timeout 仍继续轮询；不计入 last_error
            except requests.exceptions.ConnectionError:
                transient_streak += 1
            except RuntimeError as exc:
                text = str(exc)
                # 业务错误（HTTP 4xx/5xx）才记入 last_error
                if "D0005" not in text and "取件失败" not in text:
                    last_error = text
            time.sleep(interval)
        if self._auto_release():
            try:
                self.release_email(address)
            except Exception:
                pass
        if last_error:
            raise RuntimeError(f"等待验证码超时，最后错误: {last_error}")
        if transient_streak > 0:
            raise RuntimeError(
                f"等待验证码超时：连续 {transient_streak} 次轮询 read/connect 超时，请检查 mailnest.top 网络或代理"
            )
        return None

    async def wait_code(self, email: str, *, timeout: float = 120, skip_codes=None) -> str | None:
        # 不加全局锁：to_thread 已隔离阻塞 sleep，_wait_code_sync 仅操作
        # self._active[本邮箱 key]（不同邮箱 key 互不冲突，CPython GIL 保护 dict 操作）。
        # 加锁会导致 concurrency=5 时 5 个账号串行等码，退化为假并发。
        return await asyncio.to_thread(self._wait_code_sync, email, timeout, skip_codes)


PROVIDER = MailnestEmailProvider()
