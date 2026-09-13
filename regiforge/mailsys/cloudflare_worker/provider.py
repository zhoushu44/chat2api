from __future__ import annotations

import asyncio
import json
import quopri
import random
import re
import time
import urllib.parse
from email import policy
from email.parser import BytesParser
from typing import Any

import requests

from core.base import EmailProvider


class CloudflareWorkerEmailProvider(EmailProvider):
    id = "cloudflare_worker"
    name = "Cloudflare Worker"

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}

    def generate_address(self) -> str:
        domain = (
            self._config.get("cloudmail_domains")
            or self._config.get("email_domain")
            or "zhoushu.kdns.fr"
        ).strip().split(",")[0].strip()
        num = "".join(random.choice("0123456789") for _ in range(8))
        return f"{num}@{domain}"

    def _proxies(self) -> dict[str, str] | None:
        """可选 HTTP/SOCKS 代理：本机直连 Worker 超时时常需走本地代理。
        
        支持多行代理配置，自动选择第一个可用代理。
        带认证的 SOCKS5 代理会自动转换为本地 HTTP 转发器。
        """
        proxy_config = (
            self._config.get("http_proxy")
            or self._config.get("https_proxy")
            or self._config.get("proxy")
            or ""
        ).strip()
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
                "Cloudflare Worker SOCKS5 转发器创建失败，降级到 socks5h://"
            )
            netloc = f"{username}:{password}@{parsed.hostname}:{parsed.port}"
            return f"socks5h://{netloc}"

    def _request_kwargs(self, timeout: float = 10) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"timeout": timeout}
        proxies = self._proxies()
        if proxies:
            kwargs["proxies"] = proxies
        return kwargs

    def _worker_get(self, key: str) -> str | None:
        worker_url = (self._config.get("worker_url") or "").strip()
        token = (self._config.get("worker_token") or "nv2026").strip()
        if not worker_url:
            return None
        try:
            r = requests.get(
                worker_url,
                params={"token": token, "key": key},
                **self._request_kwargs(10),
            )
            if r.status_code == 200 and r.text:
                return r.text
        except Exception:
            return None
        return None

    def _cloudmail_settings(self) -> tuple[str, str, str]:
        base = str(self._config.get("cloudmail_api_base") or "").strip().rstrip("/")
        path = str(self._config.get("cloudmail_path_messages") or "/api/public/emailList").strip()
        if not path.startswith("/"):
            path = "/" + path
        api_key = str(self._config.get("cloudmail_api_key") or "").strip()
        return base, path, api_key

    @staticmethod
    def _extract_code_from_text(text: str) -> str | None:
        if not text:
            return None
        try:
            decoded = quopri.decodestring(text).decode("utf-8", errors="replace")
        except Exception:
            decoded = text
        # 去 HTML 标签，避免样式里的假数字
        plain = re.sub(r"<style[\s\S]*?</style>", " ", decoded, flags=re.I)
        plain = re.sub(r"<script[\s\S]*?</script>", " ", plain, flags=re.I)
        plain = re.sub(r"<[^>]+>", " ", plain)
        plain = re.sub(r"&nbsp;", " ", plain)
        plain = re.sub(r"\s+", " ", plain)

        patterns = [
            r"(?:your\s+)?(?:\w+\s+)?verification\s+code\s+is\s*:?\s*(\d{3})\s*[-–]\s*(\d{3})",
            r"(?:your\s+)?(?:\w+\s+)?verification\s+code\s+is\s*:?\s*(\d{6})",
            r"verification\s+code\s*(?:is)?\s*:?\s*(\d{3})\s*[-–]\s*(\d{3})",
            r"verification\s+code\s*(?:is)?\s*:?\s*(\d{6})",
            r"验证码(?:为|是)?\s*:?\s*(\d{3})\s*[-–]\s*(\d{3})",
            r"验证码(?:为|是)?\s*:?\s*(\d{6})",
            r"(?:6-digit|six[-\s]?digit)\s+code\s*:?\s*(\d{3})\s*[-–]\s*(\d{3})",
            r"(?:6-digit|six[-\s]?digit)\s+code\s*:?\s*(\d{6})",
        ]
        for pat in patterns:
            m = re.search(pat, plain, flags=re.I)
            if not m:
                continue
            if m.lastindex == 2:
                return m.group(1) + m.group(2)
            return m.group(1)

        # HTML 里常见的独立验证码块（带上下文才接受，避免误抓样式数字）
        m = re.search(r">\s*(\d{3})\s*[-–]\s*(\d{3})\s*<", decoded)
        if m:
            return m.group(1) + m.group(2)
        m = re.search(
            r"(?:code|验证码)[^0-9>]{0,40}>\s*(\d{6})\s*<",
            decoded,
            flags=re.I,
        )
        if m:
            return m.group(1)
        return None

    def _extract_code_from_message(self, message: dict[str, Any]) -> str | None:
        # 字段 code 可能是脏数据（如 156-OFN），仅接受纯数字
        raw_code = str(message.get("code") or "").strip()
        if raw_code.isdigit() and 4 <= len(raw_code) <= 8:
            return raw_code

        candidates: list[str] = []
        raw = str(message.get("raw") or message.get("content") or "")
        if raw:
            try:
                msg = BytesParser(policy=policy.default).parsebytes(
                    raw.encode("utf-8", errors="ignore")
                )
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() in ("text/html", "text/plain"):
                            try:
                                candidates.append(str(part.get_content()))
                            except Exception:
                                pass
                else:
                    try:
                        candidates.append(str(msg.get_content()))
                    except Exception:
                        pass
            except Exception:
                candidates.append(raw)

        for key in ("content", "html", "text", "body", "subject"):
            val = message.get(key)
            if val:
                candidates.append(str(val))

        for text in candidates:
            code = self._extract_code_from_text(text)
            if code:
                return code
        return None

    def _cloudmail_get_code_sync(self, email: str, timeout: float, interval: float = 2.0) -> str | None:
        """兼容原 grok-register-cloudmail 的 POST /api/public/emailList 协议。"""
        base, path, api_key = self._cloudmail_settings()
        if not (base and api_key):
            return None
        deadline = time.time() + timeout
        while time.time() < deadline:
            payload = {
                "toEmail": email,
                "type": 0,
                "isDel": 0,
                "timeSort": "desc",
                "num": 1,
                "size": 20,
            }
            try:
                response = requests.post(
                    f"{base}{path}",
                    headers={"Authorization": api_key, "Content-Type": "application/json"},
                    json=payload,
                    **self._request_kwargs(20),
                )
                if response.status_code >= 400:
                    # 鉴权/路径错误时打一次日志，避免 180s 静默空转
                    if not getattr(self, "_cloudmail_err_logged", False):
                        self._cloudmail_err_logged = True
                        print(
                            f"[cloudflare_worker] CloudMail HTTP {response.status_code}: "
                            f"{(response.text or '')[:200]}"
                        )
                else:
                    data = response.json()
                    messages = data.get("data") if isinstance(data, dict) else None
                    if not isinstance(messages, list):
                        messages = data.get("messages", []) if isinstance(data, dict) else []
                    for message in messages:
                        if not isinstance(message, dict):
                            continue
                        target = str(
                            message.get("toEmail") or message.get("to_email") or ""
                        ).strip().lower()
                        if target and target != email.lower():
                            continue
                        code = self._extract_code_from_message(message)
                        if code:
                            return code
            except Exception as exc:
                if not getattr(self, "_cloudmail_exc_logged", False):
                    self._cloudmail_exc_logged = True
                    print(f"[cloudflare_worker] CloudMail 轮询异常: {exc}")
            time.sleep(interval)
        return None

    def _kv_get(self, key: str) -> str | None:
        cf_token = (self._config.get("cf_api_token") or "").strip()
        account = (self._config.get("cf_account_id") or "").strip()
        namespace = (self._config.get("cf_kv_namespace") or "").strip()
        if not (cf_token and account and namespace):
            return None
        url = (
            f"https://api.cloudflare.com/client/v4/accounts/{account}"
            f"/storage/kv/namespaces/{namespace}/values/{urllib.parse.quote(key, safe='')}"
        )
        try:
            r = requests.get(
                url,
                headers={"Authorization": f"Bearer {cf_token}"},
                **self._request_kwargs(10),
            )
            if r.status_code == 200:
                return r.text
        except Exception:
            return None
        return None

    def _parse_code(self, val: str) -> str | None:
        try:
            data = json.loads(val)
            code = data.get("code")
            if code:
                code_s = str(code).strip()
                if code_s.isdigit():
                    return code_s
                m = re.search(r"(\d{3})\s*[-–]\s*(\d{3})", code_s)
                if m:
                    return m.group(1) + m.group(2)
                m = re.search(r"(\d{6})", code_s)
                if m:
                    return m.group(1)
        except json.JSONDecodeError:
            if val.strip().isdigit():
                return val.strip()
            return self._extract_code_from_text(val)
        return None

    # ── 验证链接提取（"点击邮件链接"验证模式）──

    @staticmethod
    def _extract_link_from_text(text: str) -> str | None:
        """从邮件文本中提取 NVIDIA 验证链接。

        优先匹配 nvidia.com 域名的 HTTPS 链接（含 verify/confirm 关键词），
        兜底匹配任意 nvidia.com 链接。

        注意：邮件正文可能用 quoted-printable 编码，= 被编码为 =3D，长 URL 会被
        软换行（= 行尾）截断。quopri.decodestring 会还原 =3D → = 并拼接软换行，
        因此优先在解码文本中搜索（拿到完整 URL），原文兜底。
        """
        if not text:
            return None
        try:
            decoded = quopri.decodestring(text.encode("utf-8", errors="ignore")).decode("utf-8", errors="replace")
        except Exception:
            decoded = text

        # 优先：nvidia.com 域 + verify/confirm/activate 关键词（先搜解码，再搜原文）
        priority_patterns = [
            r'https?://[^\s"\'<>]*nvidia\.com[^\s"\'<>]*(?:verify|confirm|activate|click|email|token)[^\s"\'<>]*',
            r'https?://[^\s"\'<>]*nvgs[^\s"\'<>]*(?:verify|confirm|activate|token)[^\s"\'<>]*',
        ]
        for source in (decoded, text):
            for pat in priority_patterns:
                m = re.search(pat, source, flags=re.I)
                if m:
                    return m.group(0).rstrip(".,;)")

        # 兜底：任意 nvidia.com HTTPS 链接（排除图片/CSS 等资源）
        general_pattern = r'https://[^\s"\'<>]*nvidia\.com[^\s"\'<>]*'
        for source in (decoded, text):
            matches = re.findall(general_pattern, source, flags=re.I)
            for url in matches:
                lower = url.lower()
                if any(ext in lower for ext in (".png", ".jpg", ".gif", ".css", ".js", ".ico", ".svg")):
                    continue
                return url.rstrip(".,;)")

        return None

    def _extract_link_from_message(self, message: dict[str, Any]) -> str | None:
        """从 CloudMail 消息中提取验证链接。"""
        candidates: list[str] = []
        raw = str(message.get("raw") or message.get("content") or "")
        if raw:
            try:
                msg = BytesParser(policy=policy.default).parsebytes(
                    raw.encode("utf-8", errors="ignore")
                )
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() in ("text/html", "text/plain"):
                            try:
                                candidates.append(str(part.get_content()))
                            except Exception:
                                pass
                else:
                    try:
                        candidates.append(str(msg.get_content()))
                    except Exception:
                        pass
            except Exception:
                candidates.append(raw)

        for key in ("content", "html", "text", "body"):
            val = message.get(key)
            if val:
                candidates.append(str(val))

        for text in candidates:
            link = self._extract_link_from_text(text)
            if link:
                return link
        return None

    def _get_link_cloudmail_sync(self, email: str, timeout: float, interval: float = 2.0) -> str | None:
        """从 CloudMail API 轮询获取验证链接。"""
        base, path, api_key = self._cloudmail_settings()
        if not (base and api_key):
            return None
        deadline = time.time() + timeout
        while time.time() < deadline:
            payload = {
                "toEmail": email,
                "type": 0,
                "isDel": 0,
                "timeSort": "desc",
                "num": 1,
                "size": 20,
            }
            try:
                response = requests.post(
                    f"{base}{path}",
                    headers={"Authorization": api_key, "Content-Type": "application/json"},
                    json=payload,
                    **self._request_kwargs(20),
                )
                if response.status_code < 400:
                    data = response.json()
                    messages = data.get("data") if isinstance(data, dict) else None
                    if not isinstance(messages, list):
                        messages = data.get("messages", []) if isinstance(data, dict) else []
                    for message in messages:
                        if not isinstance(message, dict):
                            continue
                        target = str(
                            message.get("toEmail") or message.get("to_email") or ""
                        ).strip().lower()
                        if target and target != email.lower():
                            continue
                        link = self._extract_link_from_message(message)
                        if link:
                            return link
            except Exception:
                pass
            time.sleep(interval)
        return None

    def _get_link_sync(self, email: str, timeout: float) -> str | None:
        """获取验证链接：CloudMail 优先，失败再 worker/KV。"""
        base, _, api_key = self._cloudmail_settings()
        if base and api_key:
            primary = max(timeout * 0.85, timeout - 20)
            link = self._get_link_cloudmail_sync(email, primary)
            if link:
                return link
            remain = max(5.0, timeout - primary)
            return self._get_link_worker_sync(email, remain)
        return self._get_link_worker_sync(email, timeout)

    def _get_link_worker_sync(self, email: str, timeout: float, interval: float = 1.0) -> str | None:
        """从 Worker/KV 轮询获取验证链接。"""
        key = email.lower().strip()
        deadline = time.time() + timeout
        while time.time() < deadline:
            val = self._worker_get(key) or self._kv_get(key)
            if val:
                # Worker/KV 返回的可能是 JSON 或纯文本
                try:
                    data = json.loads(val)
                    # 如果有 link/url 字段直接用
                    link = data.get("link") or data.get("url") or data.get("verify_url")
                    if link and isinstance(link, str) and link.startswith("http"):
                        return link
                    # 否则从 raw/content 提取
                    for field in ("raw", "content", "html", "text", "body"):
                        text = data.get(field)
                        if text:
                            extracted = self._extract_link_from_text(str(text))
                            if extracted:
                                return extracted
                except (json.JSONDecodeError, TypeError):
                    # 纯文本：直接提取
                    extracted = self._extract_link_from_text(val)
                    if extracted:
                        return extracted
            time.sleep(interval)
        return None

    async def wait_link(self, email: str, *, timeout: float = 120) -> str | None:
        """轮询获取验证链接（"点击邮件链接"验证模式）。"""
        return await asyncio.to_thread(self._get_link_sync, email, timeout)

    def _fetch_code_sync(self, email: str, timeout: float, interval: float = 1.0) -> str | None:
        key = email.lower().strip()
        deadline = time.time() + timeout
        while time.time() < deadline:
            val = self._worker_get(key) or self._kv_get(key)
            if val:
                code = self._parse_code(val)
                if code:
                    return code
            time.sleep(interval)
        return None

    def _get_code_sync(self, email: str, timeout: float) -> str | None:
        """CloudMail 优先（可走代理），失败再 worker/KV。"""
        base, _, api_key = self._cloudmail_settings()
        if base and api_key:
            # 给 CloudMail 大半超时；剩余再兜底 worker/KV
            primary = max(timeout * 0.85, timeout - 20)
            code = self._cloudmail_get_code_sync(email, primary)
            if code:
                return code
            remain = max(5.0, timeout - primary)
            return self._fetch_code_sync(email, remain)
        return self._fetch_code_sync(email, timeout)

    async def wait_code(self, email: str, *, timeout: float = 120) -> str | None:
        return await asyncio.to_thread(self._get_code_sync, email, timeout)


PROVIDER = CloudflareWorkerEmailProvider()
