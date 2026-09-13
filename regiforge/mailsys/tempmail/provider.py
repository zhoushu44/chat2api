"""TempMail.lol 邮箱 Provider — 临时邮箱收验证码。

通过 TempMail.lol REST API 创建临时邮箱并轮询接收 xAI 验证码。

API 端点:
    POST /v2/inbox/create  -> { address, token }  (201)
    GET  /v2/inbox?token=  -> { emails[], expired } (200)
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any

import requests
import urllib3

from core.base import EmailProvider

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://api.tempmail.lol"

# 代理配置（可选）
_proxies_config: dict[str, str] | None = None

# Microsoft 安全代码提取正则（Outlook 注册辅助邮箱验证码）。
# 以主题/正文关键词锚定，避免误伤 xAI 字母数字验证码。
_MS_CODE_PATTERNS = (
    re.compile(r"(?i)(?:安全代码|安全碼|security code|microsoft account security code|verification code|验证码|驗證碼)[^\d<>]{0,40}(\d{6})"),
)

# xAI 验证码提取正则
_CODE_PATTERNS = (
    # 当前格式: "LSQ-OPU" (3 alphanum + dash + 3 alphanum)
    re.compile(r"(?<![A-Z0-9])([A-Z0-9]{3}-[A-Z0-9]{3})(?![A-Z0-9])"),
    # 旧格式: 6 位大写字母数字，无 dash
    re.compile(r"(?<![A-Z0-9])([A-Z0-9]{6})(?![A-Z0-9])"),
    # 关键词锚定
    re.compile(
        r"(?i)(?:code|otp|验证码|verification|verify)\s*[:：]?\s*([A-Z0-9]{3}-[A-Z0-9]{3})"
    ),
    re.compile(
        r"(?i)(?:code|otp|验证码|verification|verify)\s*[:：]?\s*([A-Z0-9]{6})"
    ),
)


def _extract_code(text: str) -> str | None:
    """从邮件文本中提取验证码：优先 Microsoft 6 位安全代码，其次 xAI 格式。"""
    if not text:
        return None
    for pat in _MS_CODE_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(1)
    for pat in _CODE_PATTERNS:
        m = pat.search(text)
        if m:
            raw = m.group(1) if m.groups() else m.group(0)
            # xAI codes 是字母数字混合，不是纯数字
            if raw.replace("-", "").isdigit():
                continue
            return raw.upper()
    return None


class TempmailEmailProvider(EmailProvider):
    """TempMail.lol 临时邮箱：创建邮箱 → 轮询收件 → 提取验证码。

    配置键：email.tempmail
      - api_key: TempMail.lol API Key (Bearer token)
      - proxy: 可选，SOCKS5 代理地址（如 socks5://user:pass@host:port）
    """

    id = "tempmail"
    name = "TempMail.lol 临时邮箱"

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}
        self._active: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    def configure(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._active = {}

    def _api_key(self) -> str:
        return str(self._config.get("api_key") or "").strip()

    def _base_url(self) -> str:
        return str(self._config.get("base_url") or BASE_URL).rstrip("/")

    def _headers(self) -> dict[str, str]:
        key = self._api_key()
        if not key:
            raise RuntimeError("TempMail.lol 未配置 api_key；请在 email.tempmail.api_key 中填写")
        return {"Authorization": f"Bearer {key}"}

    def _proxies(self) -> dict[str, str] | None:
        """获取代理配置。
        
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
        
        # requests 支持 socks5:// 前缀（需要安装 requests[socks]）
        # 但 http:// 本地转发器更可靠
        return {
            "http": proxy,
            "https": proxy,
        }
    
    def _convert_socks5_proxy(self, proxy: str) -> str:
        """将带认证的 SOCKS5 代理转换为本地 HTTP 转发器。

        复用 Socks5Provider 的 _with_auth_forwarder 逻辑。
        如果转换失败，回退到 socks5h:// 格式。
        """
        if not proxy or "://" not in proxy:
            return proxy

        from urllib.parse import urlparse, unquote
        parsed = urlparse(proxy)

        # 只有带认证的 socks5:// 才需要转换
        if not parsed.scheme.lower().startswith("socks"):
            return proxy  # http:// 或其他，直接返回
        if not parsed.username and not parsed.password:
            return proxy  # 免认证 socks5，直接返回

        # URL 解码用户名密码（socks-pass%401 → socks-pass@1）
        username = unquote(parsed.username) if parsed.username else ""
        password = unquote(parsed.password) if parsed.password else ""

        try:
            # 尝试创建本地 HTTP 转发器
            from proxy.socks5.http_forwarder import Socks5HttpForwarder
            forwarder = Socks5HttpForwarder(
                remote_host=parsed.hostname,
                remote_port=parsed.port,
                username=username,
                password=password,
            )
            local_server = forwarder.start_sync()
            return local_server  # http://127.0.0.1:xxxx
        except Exception:
            # 转发器创建失败，降级到 socks5h://
            import logging
            logging.getLogger(__name__).warning(
                "TempMail SOCKS5 转发器创建失败，降级到 socks5h://"
            )
            netloc = f"{username}:{password}@{parsed.hostname}:{parsed.port}"
            return f"socks5h://{netloc}"

    def _poll_interval(self) -> float:
        try:
            return max(1.0, float(self._config.get("poll_interval") or 3))
        except (TypeError, ValueError):
            return 3.0

    def generate_address(self) -> str:
        """创建 TempMail.lol 临时邮箱（含重试）。"""
        key = self._api_key()
        if not key:
            raise RuntimeError("TempMail.lol 未配置 api_key")

        base = self._base_url()
        headers = self._headers()
        proxies = self._proxies()

        last_err = None
        for attempt in range(3):
            try:
                resp = requests.post(
                    f"{base}/v2/inbox/create",
                    headers=headers,
                    json={"prefix": "xai"},
                    timeout=15,
                    proxies=proxies,
                )
                if resp.status_code != 201:
                    last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    if attempt < 2:
                        time.sleep(3)
                        continue
                    raise RuntimeError(f"TempMail.lol create inbox failed: {last_err}")

                data = resp.json()
                address = data.get("address", "")
                token = data.get("token", "")

                if not address:
                    raise RuntimeError(f"TempMail.lol 创建邮箱返回空地址：{data!r}")

                self._active[address.lower()] = {
                    "address": address,
                    "token": token,
                    "started_at": time.time(),
                }
                return address
            except requests.exceptions.ProxyError as e:
                last_err = str(e)
                if attempt < 2:
                    time.sleep(3)
                    continue
                raise RuntimeError(f"TempMail.lol 代理连接失败（3次重试后）: {last_err}")
            except requests.exceptions.RequestException as e:
                last_err = str(e)
                if attempt < 2:
                    time.sleep(3)
                    continue
                raise RuntimeError(f"TempMail.lol 请求失败（3次重试后）: {last_err}")
        raise RuntimeError(f"TempMail.lol 创建邮箱失败: {last_err}")

    def _get_emails_sync(self, email: str) -> list[dict]:
        """获取邮箱当前所有邮件。"""
        info = self._active.get(email.lower())
        if not info:
            raise RuntimeError(f"TempMail.lol 邮箱 {email} 未创建或已过期")
        base = self._base_url()
        headers = self._headers()
        proxies = self._proxies()
        try:
            resp = requests.get(
                f"{base}/v2/inbox",
                headers=headers,
                params={"token": info["token"]},
                timeout=15,
                proxies=proxies,
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            return data.get("emails", [])
        except Exception:
            return []

    def _wait_code_sync(self, email: str, timeout: float) -> str | None:
        """轮询邮箱直到收到 xAI 验证码。"""
        deadline = time.time() + timeout
        interval = self._poll_interval()
        seen_ids: set[str] = set()

        while time.time() < deadline:
            emails = self._get_emails_sync(email)
            for mail in emails:
                eid = f"{mail.get('from','')}:{mail.get('subject','')}:{mail.get('date','')}"
                if eid in seen_ids:
                    continue
                seen_ids.add(eid)

                text = " ".join([
                    mail.get("subject", "") or "",
                    mail.get("body", "") or "",
                    mail.get("from", "") or "",
                ])
                code = _extract_code(text)
                if code:
                    self._active.pop(email.lower(), None)
                    return code

            time.sleep(interval)

        self._active.pop(email.lower(), None)
        return None

    async def wait_code(self, email: str, *, timeout: float = 120) -> str | None:
        # 不加全局锁：to_thread 已隔离阻塞 sleep，不同邮箱 key 互不冲突。
        # 加锁会导致 concurrency=N 时 N 个账号串行等码，退化为假并发。
        return await asyncio.to_thread(self._wait_code_sync, email, timeout)

    def _wait_link_sync(self, email: str, timeout: float) -> str | None:
        """轮询邮箱直到收到含验证链接的邮件，返回 NVIDIA 验证 URL。"""
        deadline = time.time() + timeout
        interval = self._poll_interval()
        seen_ids: set[str] = set()

        while time.time() < deadline:
            emails = self._get_emails_sync(email)
            for mail in emails:
                eid = f"{mail.get('from','')}:{mail.get('subject','')}:{mail.get('date','')}"
                if eid in seen_ids:
                    continue
                seen_ids.add(eid)

                # 合并 subject + body 提取链接
                text = " ".join([
                    mail.get("subject", "") or "",
                    mail.get("body", "") or "",
                    mail.get("html", "") or "",
                ])
                link = _extract_nvidia_link(text)
                if link:
                    self._active.pop(email.lower(), None)
                    return link

            time.sleep(interval)

        self._active.pop(email.lower(), None)
        return None

    async def wait_link(self, email: str, *, timeout: float = 120) -> str | None:
        """轮询获取验证链接（"点击邮件链接"验证模式）。"""
        # 不加全局锁：同 wait_code，不同邮箱 key 互不冲突。
        return await asyncio.to_thread(self._wait_link_sync, email, timeout)


def _extract_nvidia_link(text: str) -> str | None:
    """从邮件文本中提取 NVIDIA 验证链接。

    邮件 body 可能用 quoted-printable 编码（=3D 表示 =），需先解码再提取，
    否则链接里的 `code=3Dey...` 会被原样提取，导航后服务端返回 UNAUTHORIZED。
    """
    if not text:
        return None

    # 解码 quoted-printable（=3D -> =）
    import quopri
    try:
        decoded = quopri.decodestring(text.encode("utf-8", errors="ignore")).decode("utf-8", errors="replace")
    except Exception:
        decoded = text

    # 优先：nvidia.com 域 + verify/confirm/activate 关键词
    priority_patterns = [
        r'https?://[^\s"\'<>]*nvidia\.com[^\s"\'<>]*(?:verify|confirm|activate|click|email|token)[^\s"\'<>]*',
        r'https?://[^\s"\'<>]*nvgs[^\s"\'<>]*(?:verify|confirm|activate|token)[^\s"\'<>]*',
    ]
    for source in (decoded, text):
        for pat in priority_patterns:
            m = re.search(pat, source, flags=re.I)
            if m:
                return m.group(0).rstrip(".,;)")
    # 兜底：任意 nvidia.com HTTPS 链接（排除图片/CSS）
    general_pattern = r'https://[^\s"\'<>]*nvidia\.com[^\s"\'<>]*'
    for source in (decoded, text):
        matches = re.findall(general_pattern, source, flags=re.I)
        for url in matches:
            lower = url.lower()
            if any(ext in lower for ext in (".png", ".jpg", ".gif", ".css", ".js", ".ico", ".svg")):
                continue
            return url.rstrip(".,;)")
    return None


PROVIDER = TempmailEmailProvider()
