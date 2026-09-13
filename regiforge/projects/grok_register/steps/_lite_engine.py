"""grok_register lite HTTP 注册引擎 — xAI 纯协议注册（无需浏览器）。

流程（全 HTTP，无浏览器）：
  1. Bootstrap：GET 注册页获取元数据 + sitekey + next-action
  2. 创建邮箱 + 发送验证码：ctx.email + gRPC CreateEmailValidationCode
  3. 等待 + 校验验证码：ctx.email.wait_code + gRPC VerifyEmailValidationCode
  4. Turnstile + 建号：ctx.captcha 解 Turnstile + Server Action create_account
  5. 提取 SSO：RSC body → set-cookie 链 → sso JWT

来源：grok-register-lite 的 xconsole_client 模块精简适配 RegiForge 框架。
"""
from __future__ import annotations

import asyncio
import base64
import gzip
import io
import json
import os
import re
import struct
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

# ── curl_cffi transport ──────────────────────────────────────────────────

try:
    from curl_cffi import requests as cc_requests
    _HAS_CURL_CFFI = True
except Exception:
    cc_requests = None
    _HAS_CURL_CFFI = False

# ── config constants ────────────────────────────────────────────────────

CONSOLE_HOST = "console.x.ai"
ACCOUNTS_HOST = "accounts.x.ai"
ACCOUNTS_ORIGIN = "https://accounts.x.ai"
HOME_URL = "https://console.x.ai/home"
SIGNUP_URL = "https://accounts.x.ai/sign-up?redirect=grok-com"
SIGNIN_URL = "https://accounts.x.ai/sign-in?redirect=grok-com"

GRPC_SERVICE = "auth_mgmt.AuthManagement"
RPC_CREATE_CODE = f"https://accounts.x.ai/{GRPC_SERVICE}/CreateEmailValidationCode"
RPC_VERIFY_CODE = f"https://accounts.x.ai/{GRPC_SERVICE}/VerifyEmailValidationCode"
RPC_VALIDATE_PW = f"https://accounts.x.ai/{GRPC_SERVICE}/ValidatePassword"

TURNSTILE_SITEKEY = "0x4AAAAAAAhr9JGVDZbrZOo0"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)
SEC_CH_UA = '"Chromium";v="145", "Google Chrome";v="145", "Not/A)Brand";v="99"'
SEC_CH_UA_PLATFORM = '"Windows"'
ACCEPT_LANGUAGE = "zh-CN,zh;q=0.9"
CONNECT_ES_VERSION = "connect-es/2.1.1"

DEFAULT_IMPERSONATE = "chrome145"
DEFAULT_HTTP_VERSION = "v2"

# ── protobuf / gRPC-web codec ──────────────────────────────────────────

WT_VARINT = 0
WT_FIXED64 = 1
WT_LEN = 2
WT_FIXED32 = 5


def _encode_varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _tag(field_no: int, wire_type: int) -> bytes:
    return _encode_varint((field_no << 3) | wire_type)


def _encode_string(field_no: int, text: str) -> bytes:
    raw = text.encode("utf-8")
    return _tag(field_no, WT_LEN) + _encode_varint(len(raw)) + raw


def _encode_message(fields: List[Tuple[int, str]]) -> bytes:
    out = bytearray()
    for field_no, value in fields:
        out += _encode_string(field_no, value)
    return bytes(out)


def _read_varint(data: bytes, i: int) -> Tuple[int, int]:
    result = 0
    shift = 0
    while True:
        b = data[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, i
        shift += 7


def _decode_message(data: bytes) -> List[Dict[str, Any]]:
    fields: List[Dict[str, Any]] = []
    i = 0
    n = len(data)
    while i < n:
        tag, i = _read_varint(data, i)
        field_no = tag >> 3
        wt = tag & 0x07
        if wt == WT_VARINT:
            val, i = _read_varint(data, i)
            fields.append({"field": field_no, "type": "varint", "value": val})
        elif wt == WT_FIXED64:
            chunk = data[i:i + 8]; i += 8
            fields.append({"field": field_no, "type": "fixed64", "hex": chunk.hex()})
        elif wt == WT_LEN:
            ln, i = _read_varint(data, i)
            chunk = data[i:i + ln]; i += ln
            try:
                s = chunk.decode("utf-8")
                if s.isprintable():
                    fields.append({"field": field_no, "type": "string", "value": s})
                    continue
            except UnicodeDecodeError:
                pass
            fields.append({"field": field_no, "type": "bytes", "hex": chunk.hex(), "len": ln})
        elif wt == WT_FIXED32:
            chunk = data[i:i + 4]; i += 4
            fields.append({"field": field_no, "type": "fixed32", "hex": chunk.hex()})
        else:
            break
    return fields


def _frame_request(message: bytes) -> bytes:
    return b"\x00" + struct.pack(">I", len(message)) + message


def _parse_response(body: bytes) -> Dict[str, Any]:
    messages: List[List[Dict[str, Any]]] = []
    trailers: Dict[str, str] = {}
    i = 0
    n = len(body)
    while i + 5 <= n:
        flag = body[i]
        length = struct.unpack(">I", body[i + 1:i + 5])[0]
        payload = body[i + 5:i + 5 + length]
        i += 5 + length
        if flag & 0x80:
            for line in payload.decode("utf-8", "replace").split("\r\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    trailers[k.strip().lower()] = v.strip()
        else:
            messages.append(_decode_message(payload))
    grpc_status = int(trailers["grpc-status"]) if "grpc-status" in trailers else None
    return {"messages": messages, "trailers": trailers, "grpc_status": grpc_status}


# ── typed results ──────────────────────────────────────────────────────

@dataclass
class GrpcResult:
    ok: bool
    http_status: int
    grpc_status: Optional[int] = None
    messages: List[List[Dict[str, Any]]] = field(default_factory=list)
    raw: bytes = b""

    @property
    def first_message(self) -> List[Dict[str, Any]]:
        return self.messages[0] if self.messages else []


@dataclass
class SignupResult:
    ok: bool
    http_status: int
    set_cookies: List[str] = field(default_factory=list)
    rsc_body: str = ""


# ── FingerprintTransport (curl_cffi) ──────────────────────────────────

_KNOWN_ATTRS = ("Path=", "Expires=", "Max-Age=", "Domain=", "Secure", "HttpOnly",
                "SameSite=", "Partitioned")


def _split_set_cookie(joined: str) -> List[str]:
    out: List[str] = []
    cur = joined
    while True:
        if "," not in cur:
            out.append(cur.strip())
            break
        idx = _next_cookie_boundary(cur)
        if idx < 0:
            out.append(cur.strip())
            break
        out.append(cur[:idx].strip())
        cur = cur[idx + 1:].lstrip()
    return [c for c in out if c]


def _next_cookie_boundary(joined: str) -> int:
    pos = 0
    n = len(joined)
    while pos < n:
        comma = joined.find(",", pos)
        if comma < 0:
            return -1
        after = joined[comma + 1:].lstrip()
        head = joined[:comma]
        if ";" in head and after:
            if "=" in after.split(";", 1)[0]:
                first_token = after.split("=", 1)[0].strip()
                if first_token and all(c.isalnum() or c in "-_." for c in first_token):
                    return comma
        pos = comma + 1
    return -1


class FingerprintTransport:
    """curl_cffi TLS 指纹传输层，模拟 Chrome 浏览器指纹。"""

    def __init__(
        self,
        *,
        impersonate: str = DEFAULT_IMPERSONATE,
        http_version: str = DEFAULT_HTTP_VERSION,
        timeout: float = 30.0,
        debug: bool = False,
        proxy: Optional[str] = None,
    ):
        if not _HAS_CURL_CFFI:
            raise RuntimeError("curl_cffi 未安装，请运行: pip install curl_cffi")
        self._impersonate = impersonate
        self._timeout = timeout
        self._debug = debug
        self._proxy = (proxy or "").strip() or None
        self._session = cc_requests.Session(
            impersonate=impersonate,
            http_version=http_version,
        )
        self._session.headers["accept-encoding"] = "gzip, deflate, br, zstd"
        if self._proxy:
            # curl_cffi 支持 socks5:// 前缀，但需要正确配置
            # 如果是 socks5:// 格式，curl_cffi 会自动处理
            self._session.proxies = {
                "http": self._proxy,
                "https": self._proxy,
            }
            # 确保使用 socks5h:// 以启用远程 DNS（如果用户提供的是 socks5://）
            if self._proxy.startswith("socks5://"):
                # 转换为 socks5h:// 以启用远程 DNS 解析
                self._session.proxies = {
                    "http": self._proxy.replace("socks5://", "socks5h://", 1),
                    "https": self._proxy.replace("socks5://", "socks5h://", 1),
                }

    def request(
        self, method: str, url: str, *, headers: Dict[str, str], body: Optional[bytes] = None
    ) -> Tuple[int, Dict[str, str], List[str], bytes]:
        merged: Dict[str, str] = {}
        for k in ("user-agent", "accept", "accept-language", "accept-encoding",
                   "content-type", "content-length", "origin", "referer",
                   "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform"):
            if k in headers:
                merged[k] = headers[k]
        for k, v in headers.items():
            if k not in merged:
                merged[k] = v

        req_kwargs = {
            "method": method,
            "url": url,
            "headers": merged,
            "data": body,
            "timeout": self._timeout,
            "allow_redirects": False,
        }
        if self._proxy:
            req_kwargs["proxies"] = {"http": self._proxy, "https": self._proxy}
        resp = self._session.request(**req_kwargs)
        status = resp.status_code
        raw = resp.content
        ce = resp.headers.get("content-encoding", "").lower()
        if "gzip" in ce and raw[:2] == b"\x1f\x8b":
            try:
                raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
            except OSError:
                pass
        raw_sc = resp.headers.get("set-cookie", "")
        set_cookies = _split_set_cookie(raw_sc) if raw_sc else []
        hdrs = {k.lower(): v for k, v in resp.headers.items()}
        if self._debug:
            print(f"  <- {status} {method} {url}  ({len(raw)} bytes, {len(set_cookies)} set-cookie)")
        return status, hdrs, set_cookies, raw

    @property
    def cookies(self):
        c = self._session.cookies
        return c() if callable(c) else c

    def close(self):
        self._session.close()


# ── SSO extraction helpers ─────────────────────────────────────────────

def _normalize_rsc_text(rsc_body: str) -> str:
    if not rsc_body:
        return ""
    text = rsc_body
    for _ in range(3):
        nxt = (
            text.replace("\\u0026", "&")
            .replace("\\u003d", "=")
            .replace("\\u003f", "?")
            .replace("\\u002F", "/")
            .replace("\\u002f", "/")
            .replace("\\/", "/")
            .replace("\\\\/", "/")
            .replace("&amp;", "&")
            .replace("\\u0026amp;", "&")
        )
        if nxt == text:
            break
        text = nxt
    return text


def _parse_sso_from_set_cookies(set_cookies: List[str]) -> Optional[str]:
    if not set_cookies:
        return None
    for sc in set_cookies:
        if not sc:
            continue
        m = re.search(
            r'(?:^|,\s*)sso=(eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+)',
            sc, flags=re.IGNORECASE,
        )
        if m:
            return m.group(1)
    return None


def _parse_sso_token_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    text = _normalize_rsc_text(text)
    m = re.search(
        r'(?:^|[;,\s\'"\\])sso=(eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+)',
        text, flags=re.IGNORECASE | re.MULTILINE,
    )
    return m.group(1) if m else None


def _parse_all_set_cookie_urls(rsc_body: str) -> List[str]:
    if not rsc_body:
        return []
    text = _normalize_rsc_text(rsc_body)
    found: List[str] = []
    for m in re.finditer(
        r'https?://[^\s"\'<>\\]+set-cookie/?\?q='
        r'eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+',
        text, flags=re.IGNORECASE,
    ):
        url = m.group(0)
        if url not in found:
            found.append(url)
    return found


def _parse_jwt_payload(jwt: str) -> Optional[Dict[str, Any]]:
    try:
        parts = jwt.split(".")
        if len(parts) < 2:
            return None
        raw = parts[1]
        raw += "=" * (4 - len(raw) % 4)
        return json.loads(base64.urlsafe_b64decode(raw))
    except Exception:
        return None


def _read_sso_from_jar(cookies: Any) -> Optional[str]:
    if hasattr(cookies, "get"):
        for domain in (".grok.com", "grok.com", ".x.ai", "accounts.x.ai", None):
            try:
                val = cookies.get("sso", domain=domain) if domain else cookies.get("sso")
                if val:
                    return str(val)
            except Exception:
                pass
    if hasattr(cookies, "jar"):
        for cookie in cookies.jar:
            if str(getattr(cookie, "name", "")).lower() == "sso":
                val = str(getattr(cookie, "value", "") or "")
                if val:
                    return val
    return None


# ── GrokLiteClient ────────────────────────────────────────────────────

_RSC_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)')

_PRIORITY_CHUNK_PATTERNS = [
    r'06rqcsyrqa6v-',
    r'0ewiyh8jhugm9',
    r'0j2vdu-bdg~mi',
    r'0mjo1a97a5yaq',
    r'0vlulu7bwpnvs',
    r'0\.k--fzd9bco3',
]

hard_fail = (
    "error", "failed", "invalid", "denied", "blocked",
    "expired", "forbidden", "unauthorized",
)


class GrokLiteClient:
    """xAI 注册协议客户端（精简版，仅注册路径）。"""

    def __init__(
        self,
        *,
        proxy: Optional[str] = None,
        signup_url: Optional[str] = None,
        debug: bool = False,
    ):
        self.debug = debug
        self.signup_url = signup_url or SIGNUP_URL
        self._t = FingerprintTransport(
            impersonate=DEFAULT_IMPERSONATE,
            timeout=30.0,
            debug=debug,
            proxy=proxy,
        )
        self._next_action_id: Optional[str] = None
        self._next_router_state_tree: Optional[str] = None
        self._last_rsc_body: str = ""
        self._last_create_set_cookies: List[str] = []
        self.turnstile_sitekey: Optional[str] = None

    def _request(self, method, url, *, headers, body=None):
        return self._t.request(method, url, headers=headers, body=body)

    def _base_headers(self) -> Dict[str, str]:
        return {
            "user-agent": USER_AGENT,
            "accept-language": ACCEPT_LANGUAGE,
            "sec-ch-ua": SEC_CH_UA,
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": SEC_CH_UA_PLATFORM,
        }

    def _grpc_headers(self, referer: str) -> Dict[str, str]:
        h = self._base_headers()
        h.update({
            "content-type": "application/grpc-web+proto",
            "x-grpc-web": "1",
            "x-user-agent": CONNECT_ES_VERSION,
            "accept": "*/*",
            "origin": ACCOUNTS_ORIGIN,
            "referer": referer,
            "sec-fetch-site": "same-origin",
            "sec-fetch-mode": "cors",
            "sec-fetch-dest": "empty",
        })
        return h

    # ── step 1: bootstrap ───────────────────────────────────────────

    def visit_home(self) -> int:
        h = self._base_headers()
        h.update({
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "sec-fetch-site": "none", "sec-fetch-mode": "navigate",
            "sec-fetch-dest": "document", "upgrade-insecure-requests": "1",
        })
        status, _, _, _ = self._request("GET", HOME_URL, headers=h)
        return status

    def load_signup_page(self) -> int:
        h = self._base_headers()
        h.update({
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "sec-fetch-site": "same-site", "sec-fetch-mode": "navigate",
            "sec-fetch-dest": "document", "referer": "https://console.x.ai/",
        })
        status, _hdrs, _sc, raw = self._request("GET", self.signup_url, headers=h)
        html = raw.decode("utf-8", "replace")
        if status >= 400:
            preview = re.sub(r"\s+", " ", html).strip()[:300]
            raise RuntimeError(
                f"sign-up page HTTP {status}; body={preview!r}"
            )
        try:
            self._scrape_rsc_payload(html)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to extract next-action from sign-up page: {exc}"
            ) from exc
        self.turnstile_sitekey = self._scrape_turnstile_sitekey(html) or TURNSTILE_SITEKEY
        if self.debug:
            print(f"  [scrape] next-action={self._next_action_id[:16]}... "
                  f"sitekey={self.turnstile_sitekey}")
        return status

    @staticmethod
    def _scrape_turnstile_sitekey(html: str) -> Optional[str]:
        if not html:
            return None
        patterns = (
            r'sitekey["\']\s*[:=]\s*["\'](0x4[0-9A-Za-z_-]{10,})["\']',
            r'data-sitekey=["\'](0x4[0-9A-Za-z_-]{10,})["\']',
            r'(0x4AAAAA[0-9A-Za-z_-]{8,})',
        )
        for pat in patterns:
            m = re.search(pat, html, flags=re.IGNORECASE)
            if m:
                return m.group(1)
        return None

    def _scrape_rsc_payload(self, html: str) -> None:
        rsc_segments = _RSC_PUSH_RE.findall(html)

        # Extract next-router-state-tree
        router_tree = None
        for seg in rsc_segments:
            unescaped = seg.replace('\\"', '"')
            m = re.search(r'"f":\[(\[.*?\])', unescaped)
            if m:
                flight_seg = m.group(1)
                if flight_seg.startswith('[["",{"children"'):
                    depth = 0
                    tree_end = 0
                    for i, ch in enumerate(flight_seg):
                        if ch == '[':
                            depth += 1
                        elif ch == ']':
                            depth -= 1
                            if depth == 0:
                                tree_end = i + 1
                                break
                    if tree_end > 0:
                        try:
                            parsed = json.loads(flight_seg[:tree_end])
                            if isinstance(parsed, list) and len(parsed) >= 1:
                                router_tree = json.dumps(parsed[0], separators=(",", ":"))
                        except (json.JSONDecodeError, IndexError):
                            pass

        if router_tree is None:
            rsc_full = "\n".join(seg.replace('\\"', '"') for seg in rsc_segments)
            mt = re.search(
                r'\[""\s*,\s*\{[^}]*"children":[^]]*"\(app\)"[^]]*"\(auth\)"[^]]*"sign-up"[^\]]*\]'
                r'[^]]*\][^]]*\]\s*,\s*"\$undefined"\s*,\s*"\$undefined"\s*,\s*16\]',
                rsc_full,
            )
            if mt:
                router_tree = mt.group(0)
            else:
                fallback_tree = [
                    "",
                    {"children": ["(app)", {"children": ["(auth)", {"children": [
                        "sign-up", {"children": [
                            "__PAGE__?{\"redirect\":\"cloud-console\"}", {}
                        ]}
                    ]}]}]},
                    "$undefined",
                    "$undefined",
                    16,
                ]
                router_tree = json.dumps(fallback_tree, separators=(",", ":"))
        self._next_router_state_tree = quote(router_tree, safe="")

        # Extract next-action ID from JS chunks
        self._next_action_id = self._scrape_action_id(html)

    def _scrape_action_id(self, html: str) -> str:
        # 支持带查询参数的 JS URL（如 .js?dpl=xxx）
        js_urls = list(set(re.findall(r'src="(/_next/static/chunks/[^"]+\.js(?:\?[^"]*)?)"', html)))
        if not js_urls:
            raise RuntimeError("no Next.js JS chunks found on sign-up page")

        priority: List[str] = []
        rest: List[str] = []
        for url in js_urls:
            if any(re.search(p, url) for p in _PRIORITY_CHUNK_PATTERNS):
                priority.append(url)
            else:
                rest.append(url)
        ordered = priority + rest

        signup_hash: Optional[str] = None
        fallback_hash: Optional[str] = None

        def _fetch_and_search(path: str) -> Tuple[Optional[str], bool]:
            try:
                full = f"https://accounts.x.ai{path}"
                _s, _h, _sc, raw = self._request("GET", full, headers=self._base_headers())
                text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
                hashes = set(re.findall(r'"([a-f0-9]{42})"', text))
                if not hashes:
                    return (None, False)
                is_signup = any(
                    kw in text for kw in ("createUserAndSessionRequest", "emailValidationCode")
                )
                return (next(iter(hashes)), is_signup)
            except Exception:
                return (None, False)

        workers = min(8, len(ordered))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_fetch_and_search, url): url for url in ordered}
            for f in as_completed(futures):
                h, is_signup = f.result()
                if h is None:
                    continue
                if is_signup:
                    signup_hash = h
                elif fallback_hash is None:
                    fallback_hash = h

        action_hash = signup_hash or fallback_hash
        if action_hash is None:
            raise RuntimeError("Could not find the server action ID in any JS chunk")
        return action_hash

    # ── gRPC-web RPCs ───────────────────────────────────────────────

    def _grpc_call(self, url: str, fields: List[Tuple[int, str]], referer: str) -> GrpcResult:
        message = _encode_message(fields)
        body = _frame_request(message)
        headers = self._grpc_headers(referer)
        headers["content-length"] = str(len(body))
        status, resp_headers, _, raw = self._request("POST", url, headers=headers, body=body)
        if not raw:
            # 空响应体：检查 HTTP 头中的 grpc-status（Connect/gRPC-Web unary 模式）
            hdr_grpc = resp_headers.get("grpc-status")
            grpc_st = int(hdr_grpc) if hdr_grpc is not None else None
            return GrpcResult(
                ok=(status == 200 and (grpc_st == 0 or grpc_st is None and status == 200)),
                http_status=status,
                grpc_status=grpc_st if grpc_st is not None else (0 if status == 200 else None),
                raw=raw,
            )
        parsed = _parse_response(raw)
        grpc_st = parsed["grpc_status"]
        # 若 body trailer 里没有 grpc-status，回退到 HTTP 响应头
        if grpc_st is None:
            hdr_grpc = resp_headers.get("grpc-status")
            if hdr_grpc is not None:
                grpc_st = int(hdr_grpc)
        # HTTP 200 且仍无 grpc-status -> 视为成功（Connect unary 空响应）
        if grpc_st is None and status == 200:
            grpc_st = 0
        return GrpcResult(
            ok=(status == 200 and grpc_st == 0),
            http_status=status,
            grpc_status=grpc_st,
            messages=parsed["messages"],
            raw=raw,
        )

    def create_email_validation_code(self, email: str) -> GrpcResult:
        return self._grpc_call(RPC_CREATE_CODE, [(1, email)], self.signup_url)

    def verify_email_validation_code(self, email: str, code: str) -> GrpcResult:
        return self._grpc_call(RPC_VERIFY_CODE, [(1, email), (2, code)], self.signup_url)

    def validate_password(self, email: str, password: str) -> GrpcResult:
        return self._grpc_call(RPC_VALIDATE_PW, [(4, email), (5, password)], self.signup_url)

    # ── account creation ────────────────────────────────────────────

    def create_account(
        self,
        *,
        email: str,
        given_name: str,
        family_name: str,
        password: str,
        email_validation_code: str,
        turnstile_token: str,
        castle_request_token: str = "",
        conversion_id: str = "",
    ) -> SignupResult:
        create_req = {
            "email": email,
            "givenName": given_name,
            "familyName": family_name,
            "clearTextPassword": password,
            "tosAcceptedVersion": "$undefined",
        }
        args = [
            {
                "emailValidationCode": email_validation_code,
                "createUserAndSessionRequest": create_req,
                "turnstileToken": turnstile_token,
                "conversionId": conversion_id or str(uuid.uuid4()),
                "castleRequestToken": castle_request_token,
            },
            {"client": "$T", "meta": "$undefined", "mutationKey": "$undefined"},
        ]
        body = json.dumps(args, separators=(",", ":")).encode("utf-8")

        h = self._base_headers()
        h.update({
            "accept": "text/x-component",
            "content-type": "text/plain;charset=UTF-8",
            "next-action": self._next_action_id,
            "next-router-state-tree": self._next_router_state_tree,
            "origin": ACCOUNTS_ORIGIN,
            "referer": self.signup_url,
            "sec-fetch-site": "same-origin",
            "sec-fetch-mode": "cors",
            "sec-fetch-dest": "empty",
            "content-length": str(len(body)),
        })
        status, resp_headers, set_cookies, raw = self._request(
            "POST", self.signup_url, headers=h, body=body
        )
        rsc_body = raw.decode("utf-8", "replace")
        self._last_rsc_body = rsc_body
        self._last_create_set_cookies = list(set_cookies or [])

        hard_error = bool(_extract_signup_error(rsc_body))
        ok = status == 200 and not hard_error

        if self.debug:
            print(f"  [create_account] HTTP {status} ok={ok} "
                  f"set_cookies={len(set_cookies or [])} body_len={len(rsc_body)}")

        return SignupResult(
            ok=ok, http_status=status,
            set_cookies=set_cookies,
            rsc_body=rsc_body,
        )

    # ── SSO extraction ──────────────────────────────────────────────

    def fetch_sso_token(self, *, retries: int = 3) -> Optional[str]:
        """提取 SSO token；建号后的 cookie 传播可能延迟，按 retries 重试。"""
        for attempt in range(max(1, retries)):
            token = self._fetch_sso_token_once()
            if token:
                return token
            if attempt + 1 < retries:
                time.sleep(2.0 * (attempt + 1))
        return None

    def _fetch_sso_token_once(self) -> Optional[str]:
        """从 RSC body / set-cookie 链 / fallback 页面提取一次 SSO。"""
        token = _parse_sso_from_set_cookies(self._last_create_set_cookies)
        if token:
            if self.debug:
                print("  [sso] found in create_account Set-Cookie")
            return token

        rsc_text = self._last_rsc_body
        if not token and rsc_text:
            token = _parse_sso_token_from_text(rsc_text)
            if token:
                if self.debug:
                    print("  [sso] found raw sso token in RSC body")
                return token

        # Follow set-cookie chain
        hop_urls = _parse_all_set_cookie_urls(rsc_text)
        expanded_hops = list(hop_urls)
        for hop in hop_urls:
            jwt_match = re.search(
                r'q=(eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+)',
                hop,
            )
            if not jwt_match:
                continue
            payload = _parse_jwt_payload(jwt_match.group(1))
            success_url = (payload or {}).get("config", {}).get("success_url")
            if isinstance(success_url, str) and success_url.startswith("https://") and success_url not in expanded_hops:
                expanded_hops.append(success_url)
        hop_urls = expanded_hops
        if hop_urls:
            headers = self._base_headers()
            headers.update({
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "sec-fetch-site": "cross-site",
                "sec-fetch-mode": "navigate",
                "sec-fetch-dest": "document",
                "referer": ACCOUNTS_ORIGIN + "/",
            })
            for hop in hop_urls:
                try:
                    _status, _hdrs, set_cookies, _raw = self._request("GET", hop, headers=headers)
                    token = _parse_sso_from_set_cookies(set_cookies or [])
                    if not token:
                        token = _parse_sso_token_from_text(
                            (_raw or b"").decode("utf-8", "replace")
                        )
                    if not token:
                        token = _read_sso_from_jar(self._t.cookies)
                    if token:
                        if self.debug:
                            print(f"  [sso] extracted from hop {hop[:64]}")
                        return token
                except Exception as exc:
                    if self.debug:
                        print(f"  [sso] hop failed: {exc}")

        # Fallback: visit grok.com / accounts.x.ai
        if self.debug:
            print("  [sso] entering fallback phase")
        for url, label in (
            ("https://auth.x.ai/set-cookie", "auth.x.ai"),
            ("https://auth.grokusercontent.com/set-cookie", "grokusercontent"),
            ("https://grok.com/", "grok.com"),
            (ACCOUNTS_ORIGIN + "/", "accounts.home"),
            (SIGNIN_URL, "accounts.signin"),
            (SIGNUP_URL, "accounts.signup"),
        ):
            token = self._fetch_sso_via_url(url, label=label)
            if token:
                if self.debug:
                    print(f"  [sso] found via fallback {label}")
                return token

        jar_token = _read_sso_from_jar(self._t.cookies)
        if jar_token and self.debug:
            print("  [sso] found in cookie jar")
        return jar_token

    def _fetch_sso_via_url(self, url: str, *, label: str = "") -> Optional[str]:
        headers = self._base_headers()
        headers.update({
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "sec-fetch-site": "cross-site",
            "sec-fetch-mode": "navigate",
            "sec-fetch-dest": "document",
            "referer": ACCOUNTS_ORIGIN + "/",
        })
        try:
            status, hdrs, set_cookies, raw = self._request("GET", url, headers=headers)
            if self.debug:
                print(f"  [_fetch_sso_via_url] {label} HTTP {status} url={url[:64]} set_cookies={len(set_cookies or [])} body_len={len(raw or b'')}")
                for sc in (set_cookies or [])[:5]:
                    print(f"    set-cookie: {sc[:100]}")
            token = _parse_sso_from_set_cookies(set_cookies or [])
            if token:
                return token
            body = (raw or b"").decode("utf-8", "replace")
            token = _parse_sso_token_from_text(body)
            if token:
                return token
            # follow one redirect
            loc = ""
            if isinstance(hdrs, dict):
                loc = str(hdrs.get("location") or "")
            if loc.startswith("http"):
                _s2, _h2, sc2, raw2 = self._request("GET", loc, headers=headers)
                token = (
                    _parse_sso_from_set_cookies(sc2 or [])
                    or _parse_sso_token_from_text((raw2 or b"").decode("utf-8", "replace"))
                )
                if token:
                    return token
        except Exception:
            pass
        return _read_sso_from_jar(self._t.cookies)

    def close(self):
        self._t.close()


# ── signup error extraction ──────────────────────────────────────────

def _extract_signup_error(rsc_body: str) -> Optional[str]:
    text = rsc_body or ""
    if not text:
        return None
    text_l = text.lower()
    m = re.search(r"(?m)^(\d+):E\{([^}]{0,400})", text)
    if m:
        return f"next_action_error:{m.group(2)[:160]}"
    m = re.search(r"\[?\s*wke\s*=\s*([a-z0-9_.:/-]+)\s*\]?", text_l, flags=re.IGNORECASE)
    if m:
        return f"wke={m.group(1)}"
    code_patterns = (
        r"\b(turnstile_failed)\b", r"\b(account_signup_error)\b",
        r"\b(rate_limited)\b", r"\b(validation_error)\b",
        r"\b(invalid_verification_code)\b", r"\b(email_already_in_use)\b",
        r"\b(user_already_exists)\b", r"\b(account_email_domain_rejected)\b",
        r"\b(form_invalid_disposable_email)\b",
    )
    for pat in code_patterns:
        m = re.search(pat, text_l, flags=re.IGNORECASE)
        if m:
            return m.group(1)
    return None


# ── public entry: register_lite ──────────────────────────────────────

LogFn = Callable[[str], None]
WaitCodeFn = Callable[[str, float], Any]  # (email, timeout) -> coroutine -> str|None
SolveTurnstileFn = Callable[..., Any]     # (sitekey=, page_url=) -> coroutine -> str|None


async def register_lite(
    *,
    proxy: Optional[str] = None,
    mail_timeout: float = 120.0,
    turnstile_timeout: float = 180.0,
    user_agent: Optional[str] = None,
    generate_address: Callable[[], Any],   # ctx.email.generate_address -> coroutine -> str
    wait_code: WaitCodeFn,
    solve_turnstile: SolveTurnstileFn,
    log: LogFn | None = None,
) -> dict[str, str]:
    """xAI lite HTTP 注册入口（全协议，无浏览器）。

    返回: {"email": ..., "password": ..., "sso": ..., "error": ...}
    """
    def _log(msg: str):
        if log:
            log(msg)

    c = GrokLiteClient(proxy=proxy, debug=False)

    email = ""
    password = ""
    sso = None

    try:
        # 1. Bootstrap（curl_cffi 同步 HTTP，必须 to_thread 否则阻塞事件循环）
        await asyncio.to_thread(c.visit_home)
        await asyncio.to_thread(c.load_signup_page)
        _log("cookie + scrape OK")

        # 2. 创建邮箱
        email = await generate_address()
        password = f"Pw{os.urandom(6).hex()}!a#A"
        _log(f"email: {email}")

        # 3. 发送验证码
        res_code = await asyncio.to_thread(c.create_email_validation_code, email)
        if not res_code.ok:
            raise RuntimeError(
                f"CreateEmailValidationCode failed: HTTP {res_code.http_status} "
                f"gRPC {res_code.grpc_status}"
            )
        _log("验证码已发送")

        # 4. 等待验证码
        code = await wait_code(email, mail_timeout)
        if not code:
            raise RuntimeError(f"等待验证码超时（{mail_timeout}s）")
        _log(f"code: {code}")

        # 5. 校验验证码
        res_verify = await asyncio.to_thread(c.verify_email_validation_code, email, code)
        if not res_verify.ok:
            raw_preview = res_verify.raw[:200].hex() if res_verify.raw else "(empty)"
            detail = {
                "http_status": res_verify.http_status,
                "grpc_status": res_verify.grpc_status,
                "messages": res_verify.messages,
                "raw_hex_preview": raw_preview,
            }
            raise RuntimeError(f"VerifyEmailValidationCode failed: {detail}")
        _log("email verified")

        # 6. 密码校验（可选，不阻塞主流程）
        try:
            await asyncio.to_thread(c.validate_password, email, password)
        except Exception:
            pass

        # 7. 解 Turnstile
        sitekey = c.turnstile_sitekey or TURNSTILE_SITEKEY
        turnstile_token = await solve_turnstile(
            sitekey=sitekey,
            page_url=c.signup_url,
        )
        if not turnstile_token:
            raise RuntimeError("Turnstile 解码失败")
        _log(f"Turnstile {len(turnstile_token)} chars")

        # 8. 创建账号
        res_signup = await asyncio.to_thread(
            c.create_account,
            email=email,
            given_name="Test",
            family_name="User",
            password=password,
            email_validation_code=code,
            turnstile_token=turnstile_token,
        )
        if not res_signup.ok:
            err = _extract_signup_error(res_signup.rsc_body) or f"HTTP {res_signup.http_status}"
            raise RuntimeError(f"create_account failed: {err}")
        _log("account created")

        # 9. 提取 SSO（内部有 time.sleep 重试，必须 to_thread）
        sso = await asyncio.to_thread(c.fetch_sso_token, retries=3)
        if not sso:
            raise RuntimeError("SSO extraction failed")
        _log("SSO saved")

        return {
            "email": email,
            "password": password,
            "sso": sso,
            "error": "",
        }

    except Exception as exc:
        _log(f"ERROR: {exc}")
        return {
            "email": email,
            "password": password,
            "sso": sso or "",
            "error": str(exc),
        }
    finally:
        c.close()
