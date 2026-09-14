"""ChatGPT HTTP 注册引擎（改编自 oumiFree/blackcat_engine.register）。

流程：Sentinel → CSRF → signin → OAuth 跳转 → 邮箱 OTP（ctx.email）→
create_account → session / accessToken。

邮箱/代理不在本文件实现，一律由调用方注入。
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import random
import re
import secrets
import string
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs, urlencode, urlparse

from core.models import ProxyInfo

from ._fingerprint import detect_country, generate_fingerprint, fingerprint_from_user_ua
from ._sentinel import extract_sentinel, impersonate_for_ua, sec_ch_ua_for
from ._sentinel_v8 import SentinelVMError as _SentinelVMError

try:
    from ._sentinel_v8 import build_first_sentinel_v8 as _build_first_v8
except Exception:  # pragma: no cover
    _build_first_v8 = None


def _egress_log_path() -> Path:
    """出口观测日志：data/keys/chatgpt_register/egress.jsonl（与 accounts.jsonl 同目录）。"""
    from core.paths import KEYS_DIR

    folder = KEYS_DIR / "chatgpt_register"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "egress.jsonl"


def _append_egress(rec: dict) -> None:
    """追加一条出口观测（JSONL，O_APPEND 原子写）。

    记录每次注册尝试的出口国家/时区/指纹与结果，用于统计"哪个出口好"。
    失败/重试也记录（失败样本才是出口质量的关键），异常吞掉不影响注册主流程。
    """
    try:
        import os as _os

        line = (json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8")
        _fd = _os.open(str(_egress_log_path()), _os.O_WRONLY | _os.O_APPEND | _os.O_CREAT, 0o644)
        try:
            _os.write(_fd, line)
        finally:
            _os.close(_fd)
    except Exception:
        pass


def _proxy_host_for_log(proxy_url: str | None) -> str:
    """日志用的代理标识（去认证信息）。"""
    if not proxy_url:
        return "direct"
    try:
        p = urlparse(proxy_url)
        return f"{p.scheme}://{p.hostname or '?'}:{p.port or ''}"
    except Exception:
        return (proxy_url or "direct")[:64]


def _is_curl_timeout(exc: BaseException) -> bool:
    """判断异常是否为 curl_cffi 超时错误。"""
    msg = str(exc).lower()
    return "timed out" in msg or "curl: (28)" in msg or "timeout" in type(exc).__name__.lower()


def _decode_jwt_plan_type(access_token: str) -> str:
    """解码 access_token JWT，提取 chatgpt_plan_type（free/plus/pro/team...）。

    claim 路径：payload["https://api.openai.com/auth"]["chatgpt_plan_type"]。
    解码失败或字段缺失返回空串。
    """
    try:
        payload_part = str(access_token or "").split(".")[1]
        payload_part += "=" * ((4 - len(payload_part) % 4) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_part.encode("ascii")))
        auth_claim = payload.get("https://api.openai.com/auth") or {}
        return str(auth_claim.get("chatgpt_plan_type") or "").strip()
    except Exception:
        return ""


AUTH_BASE = "https://auth.openai.com"
CHAT_BASE = "https://chatgpt.com"
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
# ── 浏览器指纹（方案 A 对齐 + A+ 随机化）────────────────────────
# A：UA 与 TLS 指纹/Client Hints 同版本，否则被判定非浏览器（UA 可配置时
#   由 impersonate_for_ua / sec_ch_ua_for 动态对齐）。
# A+：未配置 UA 时每次注册随机一套完整指纹（_fingerprint.generate_fingerprint）。
DEFAULT_IMPERSONATE = "chrome131"
# 真实 Chrome 导航请求的 Accept 与 upgrade-insecure-requests
NAV_ACCEPT = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,"
    "image/avif,image/webp,image/apng,*/*;q=0.8,"
    "application/signed-exchange;v=b3;q=0.7"
)
NAMES_FIRST = [
    "James", "John", "Robert", "Michael", "David", "William",
    "Mary", "Linda", "Barbara", "Jennifer", "Elizabeth", "Susan",
]
NAMES_LAST = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia",
    "Miller", "Davis", "Wilson", "Anderson", "Taylor", "Thomas",
]

LogFn = Callable[[str], None]
WaitCodeFn = Callable[[str], Awaitable[str | None]]


def _require_curl_cffi():
    try:
        from curl_cffi import requests as curl_requests  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "HTTP 注册模式需要 curl_cffi，请执行: pip install curl_cffi"
        ) from exc
    return curl_requests


def _proxy_url(proxy_info: ProxyInfo | None) -> str | None:
    """转为 curl_cffi 可用的代理 URL。

    Windows 上 socks5:// 经 curl_cffi 常 TLS(35)；socks5h:// 实测正常。
    HTTP/HTTPS 代理直接传递，curl_cffi 原生支持。
    """
    if not proxy_info or not (proxy_info.server or "").strip():
        return None
    server = proxy_info.server.strip()
    lower = server.lower()

    # HTTP/HTTPS 代理直接传递（含认证）
    if lower.startswith("http://") or lower.startswith("https://"):
        return server

    # SOCKS5 代理的 socks5:// → socks5h:// 转换
    if "://" not in server:
        server = f"socks5h://{server}"
    if lower.startswith("socks5://"):
        server = "socks5h://" + server[len("socks5://") :]
    if proxy_info.username and proxy_info.password:
        parsed = urlparse(server)
        netloc = f"{proxy_info.username}:{proxy_info.password}@{parsed.hostname}"
        if parsed.port:
            netloc += f":{parsed.port}"
        server = parsed._replace(netloc=netloc).geturl()
    return server


def _parse_csrf(set_cookie: str) -> str:
    m = re.search(r"__Host-next-auth\.csrf-token=([^;]+)", set_cookie or "")
    if not m:
        return ""
    # cookie 值是 token%7Chash，只要 token 段
    return m.group(1).split("%7C")[0]


def _csrf_from_response(resp) -> str:
    """优先读 /api/auth/csrf JSON 的 csrfToken；其次 Set-Cookie；禁止回退成 'true'。"""
    try:
        data = resp.json() if resp is not None else {}
        token = str((data or {}).get("csrfToken") or "").strip()
        if token and token.lower() != "true":
            return token
    except Exception:
        pass
    headers = getattr(resp, "headers", None) or {}
    # curl_cffi 可能把多个 Set-Cookie 合并/拆开
    chunks: list[str] = []
    try:
        for k, v in headers.items():
            if str(k).lower() == "set-cookie" and v:
                chunks.append(str(v))
    except Exception:
        sc = headers.get("Set-Cookie", "") if hasattr(headers, "get") else ""
        if sc:
            chunks.append(str(sc))
    for chunk in chunks:
        token = _parse_csrf(chunk)
        if token and token.lower() != "true":
            return token
    return ""


def _apply_sentinel_cookies(session, cookie_str: str, *, oai_did: str = "") -> None:
    """把 Sentinel 浏览器 cookie 挂到 openai/auth/chatgpt 相关域。

    2026-07 起 authorize 在仅 .openai.com cookie 时易 403 CF；多域 + 显式 oai-did 更稳。
    """
    domains = (
        ".openai.com",
        ".auth.openai.com",
        "auth.openai.com",
        ".chatgpt.com",
        "chatgpt.com",
    )
    skip_prefixes = ("oai-login-csrf", "oai-did", "oai-client-auth", "auth-session")
    for pair in (cookie_str or "").split("; "):
        if "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        if any(k.startswith(p) for p in skip_prefixes):
            continue
        for d in domains:
            try:
                session.cookies.set(k, v, domain=d)
            except Exception:
                pass
    did = (oai_did or "").strip()
    if did:
        for d in domains:
            try:
                session.cookies.set("oai-did", did, domain=d)
            except Exception:
                pass


def _random_name() -> tuple[str, str]:
    return random.choice(NAMES_FIRST), random.choice(NAMES_LAST)


def _random_birthdate() -> str:
    return f"{random.randint(1985, 2004)}-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}"


def _gen_password() -> str:
    chars = string.ascii_letters + string.digits
    return "".join(random.choices(chars, k=10)) + "!A1"


def _browser_headers(fp: dict[str, Any], accept: str) -> dict[str, str]:
    """按 A+ 随机指纹生成浏览器请求头（一次注册内与 Sentinel 浏览器一致）。

    真实 Chrome 必带 Client Hints（sec-ch-ua*）与 sec-fetch-*，缺失即暴露自动化。
    firefox/safari 家族不发 sec-ch-ua*（真实浏览器行为）；sec-fetch-site/mode/dest
    默认按同源 API 调用（cors/empty）填充，调用方可覆盖。
    """
    headers = {
        "User-Agent": fp["user_agent"],
        "Accept": accept,
        "Accept-Language": fp.get("accept_language", "en-US,en;q=0.9"),
        "sec-fetch-site": "same-origin",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
    }
    if fp.get("sec_ch_ua"):
        headers["sec-ch-ua"] = fp["sec_ch_ua"]
    if fp.get("sec_ch_ua_mobile"):
        headers["sec-ch-ua-mobile"] = fp["sec_ch_ua_mobile"]
    if fp.get("sec_ch_ua_platform"):
        headers["sec-ch-ua-platform"] = fp["sec_ch_ua_platform"]
    # Client Hints 全套字段（真实 Chrome 收到 Accept-CH 后回发；仅 chrome 家族有值）
    if fp.get("sec_ch_ua_full_version_list"):
        headers["sec-ch-ua-full-version-list"] = fp["sec_ch_ua_full_version_list"]
    if fp.get("sec_ch_ua_arch"):
        headers["sec-ch-ua-arch"] = fp["sec_ch_ua_arch"]
    if fp.get("sec_ch_ua_bitness"):
        headers["sec-ch-ua-bitness"] = fp["sec_ch_ua_bitness"]
    if fp.get("sec_ch_ua_model"):
        headers["sec-ch-ua-model"] = fp["sec_ch_ua_model"]
    if fp.get("sec_ch_ua_platform_version"):
        headers["sec-ch-ua-platform-version"] = fp["sec_ch_ua_platform_version"]
    if fp.get("sec_ch_ua_wow64"):
        headers["sec-ch-ua-wow64"] = fp["sec_ch_ua_wow64"]
    return headers


def _req_kwargs(proxy_url: str | None, *, fp: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    """每个请求都带上 proxy=socks5h://...（请求级参数，session.proxies 不可靠）。

    fp 非空时 TLS 指纹（impersonate）取指纹的精确版本，与 UA 严格一致。
    """
    kw: dict[str, Any] = {
        "impersonate": fp["impersonate"] if fp else DEFAULT_IMPERSONATE,
        "timeout": 30,
    }
    kw.update(extra)
    if proxy_url:
        kw["proxy"] = proxy_url
    return kw


def _oauth_get_tokens(
    session,
    *,
    email: str,
    oai_did: str,
    fp: dict[str, Any],
    proxy_url: str | None,
    log: LogFn,
) -> dict | None:
    """Codex OAuth 授权码交换 refresh_token（对齐 gpt-outlook-register v0.5.5）。

    注册会话刚建好（OTP + create_account 刚做完），auth.openai.com 有登录态，
    用 Codex client_id + codex_cli_simplified_flow 重新授权并捕获 callback code。
    注意：不要带 screen_hint/max_age=0——会强制重新认证、被打回登录页拿不到 code。
    """
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    client_id = "app_EMoamEEZ73f0CkXaXp7hrann"  # Codex CLI（v0.5.5 实测可用）
    redirect_uri = "http://localhost:1455/auth/callback"
    state = secrets.token_urlsafe(24)
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": "openid email profile offline_access",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
        "prompt": "login",
    }
    auth_url = f"{AUTH_BASE}/oauth/authorize?{urlencode(params)}"
    session.cookies.set("oai-did", oai_did or "", domain=".auth.openai.com")
    nav_headers = _browser_headers(fp, NAV_ACCEPT)
    nav_headers.update(
        {
            "Referer": "https://chatgpt.com/",
            "upgrade-insecure-requests": "1",
            "sec-fetch-site": "cross-site",
            "sec-fetch-mode": "navigate",
            "sec-fetch-dest": "document",
        }
    )

    # 手动跟随跳转，捕获 callback code（注册会话有登录态，期望直接 302 到 callback）
    no_prompt_auth_url = f"{AUTH_BASE}/oauth/authorize?{urlencode({k: v for k, v in params.items() if k != 'prompt'})}"
    cur = auth_url
    code = ""
    add_phone_retries = 0
    for hop in range(20):
        if "/auth/callback" in (cur or "").lower():
            try:
                code = str((parse_qs(urlparse(cur).query).get("code") or [""])[0]).strip()
            except Exception:
                code = ""
            if code:
                break
        try:
            r = session.get(cur, headers=nav_headers, allow_redirects=False, **_req_kwargs(proxy_url, fp=fp, timeout=45))
        except Exception as exc:
            log(f"  [OAuth] hop{hop} 请求异常: {str(exc)[:140]}")
            return None
        final = str(getattr(r, "url", cur) or cur)
        loc = r.headers.get("Location", "") or ""
        log(f"  [OAuth] hop{hop} status={r.status_code} path={final[:110]} loc={(loc or '')[:70]}")
        if r.status_code >= 400:
            return None
        if r.status_code == 200:
            final_low = (final or "").lower()
            # /add-phone：Codex 授权强制绑手机；去 prompt 刷新重试（v0.5.5 策略）
            if "/add-phone" in final_low:
                if add_phone_retries >= 2:
                    log("  [OAuth] add-phone 重试耗尽，放弃 refresh_token")
                    return None
                add_phone_retries += 1
                log(f"  [OAuth] 命中 add-phone，去 prompt 重试 ({add_phone_retries}/2)...")
                time.sleep(1.2)
                cur = no_prompt_auth_url
                continue
            # /choose-an-account：注册会话含多账号身份，需主动选第一个（v0.5.5）
            if "/choose-an-account" in final_low:
                log("  [OAuth] choose-an-account 选第一个会话...")
                m = re.search(r"us_[A-Za-z0-9]{16,}", r.text or "")
                if not m:
                    log("  [OAuth] choose-an-account HTML 未找到 us_*，放弃")
                    return None
                sel_headers = {
                    **_browser_headers(fp, "application/json"),
                    "Origin": AUTH_BASE,
                    "Referer": f"{AUTH_BASE}/choose-an-account",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                }
                try:
                    sr = session.post(
                        f"{AUTH_BASE}/api/accounts/session/select",
                        json={"session_id": m.group(0)},
                        headers=sel_headers,
                        **_req_kwargs(proxy_url, fp=fp),
                    )
                except Exception as exc:
                    log(f"  [OAuth] session/select 异常: {str(exc)[:120]}")
                    return None
                next_url = ""
                try:
                    next_url = str(sr.json().get("continue_url") or "")
                except Exception:
                    pass
                if not next_url:
                    next_url = sr.headers.get("Location", "") or ""
                log(
                    f"  [OAuth] session/select status={sr.status_code} "
                    f"next={next_url[:100] or '(无，cookie 已 set 重试 authorize)'}"
                )
                if next_url:
                    cur = next_url if next_url.startswith("http") else (
                        f"{AUTH_BASE}{next_url}" if next_url.startswith("/") else next_url
                    )
                    continue
                if sr.status_code in (200, 400):
                    # 200=无 continue_url（cookie 已 set）；400=TLS 双发后重复 select
                    # 都重走 authorize，等下一跳
                    cur = auth_url
                    continue
                return None
            # 其它 200 中间页（workspace/consent 等）未实现交互，记录并退出
            log(f"  [OAuth] 200 中间页（未实现交互）: {final[:120]}")
            return None
        if not loc:
            break
        cur = loc if loc.startswith("http") else (f"{AUTH_BASE}{loc}" if loc.startswith("/") else loc)
    if not code:
        log(f"  [OAuth] 未获取到 authorization code（最后: {cur[:140]}）")
        return None

    # token exchange（v0.5.5: https://auth.openai.com/oauth/token）
    r = session.post(
        f"{AUTH_BASE}/oauth/token",
        data=urlencode(
            {
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            }
        ),
        headers={
            **_browser_headers(fp, "application/json"),
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": AUTH_BASE,
            "Referer": f"{AUTH_BASE}/sign-in-with-chatgpt/codex/consent",
        },
        **_req_kwargs(proxy_url, fp=fp),
    )
    if r.status_code == 200:
        return r.json()
    log(f"  [OAuth] token exchange 失败 [{r.status_code}]: {r.text[:200]}")
    return None


class RetriableRegisterError(RuntimeError):
    """可整段重试的注册失败（新 Sentinel + 新会话）。"""


# ── TLS 握手瞬断重试（吸收 gpt-outlook-register v0.5.5 _TlsRetrySession）──
_TLS_ERROR_MARKERS = ("curl: (35)", "tls connect error", "openssl_internal", "sslerror")


def _is_tls_handshake_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(m in msg for m in _TLS_ERROR_MARKERS)


class _TlsRetrySession:
    """给 curl_cffi Session 的 get/post 套一层 TLS 瞬断重试，其余属性原样透传。

    代理链路偶发 `curl: (35) TLS connect error ... OPENSSL_internal`，连请求都没发出
    就炸（v0.5.5 实测发生率 5.4%，与指纹/域名无关，属链路级瞬断）。
    必须**原 session** 重试：session 里装着 oai-did/csrf，重建直接 409 invalid_state。
    实测原 session 重试 8/8 一次恢复。
    """

    def __init__(self, inner, retries: int = 2, backoff: float = 1.5, log: LogFn | None = None):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_retries", max(0, int(retries)))
        object.__setattr__(self, "_backoff", float(backoff))
        object.__setattr__(self, "_log", log or (lambda m: None))

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_inner"), name)

    def __setattr__(self, name, value):
        setattr(object.__getattribute__(self, "_inner"), name, value)

    def __iter__(self):
        return iter(object.__getattribute__(self, "_inner"))

    def _call_with_retry(self, method: str, *args, **kwargs):
        inner = object.__getattribute__(self, "_inner")
        retries = object.__getattribute__(self, "_retries")
        backoff = object.__getattribute__(self, "_backoff")
        _log = object.__getattribute__(self, "_log")
        fn = getattr(inner, method)
        for attempt in range(retries + 1):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                # 只兜 TLS 瞬断：超时/HTTP 错误/业务异常一律原样抛，别把服务端明确拒绝
                # 也变成重试，反而更像异常流量。
                if not _is_tls_handshake_error(exc) or attempt >= retries:
                    raise
                wait = backoff * (attempt + 1)
                url = args[0] if args else kwargs.get("url", "?")
                _log(f"TLS 瞬断，{wait:.1f}s 后原 session 重试 ({attempt + 1}/{retries}): {str(url)[:80]}")
                time.sleep(wait)

    def get(self, *args, **kwargs):
        return self._call_with_retry("get", *args, **kwargs)

    def post(self, *args, **kwargs):
        return self._call_with_retry("post", *args, **kwargs)


# ── RFC 6238 TOTP（2FA 绑定用）────────────────────────────────────
def _totp_now(secret_b32: str) -> str:
    """当前 30 秒窗口的 6 位 TOTP 码。"""
    import hmac as _hmac
    import struct as _struct

    pad = "=" * ((8 - len(secret_b32) % 8) % 8)
    key = base64.b32decode((secret_b32.upper() + pad).encode("ascii"))
    digest = _hmac.new(key, _struct.pack(">Q", int(time.time()) // 30), hashlib.sha1).digest()
    o = digest[-1] & 0x0F
    code = (int.from_bytes(digest[o:o + 4], "big") & 0x7FFFFFFF) % 1000000
    return f"{code:06d}"


# ── QuickJS PoW：按 flow 现算 sentinel（吸收 v0.5.5）──────────────
def _quickjs_fp_kwargs(fp: dict[str, Any]) -> dict[str, Any]:
    screen = fp.get("screen") or [1920, 1080]
    return {
        "user_agent": fp.get("user_agent") or "",
        "screen": f"{screen[0]}x{screen[1]}",
        "lang": fp.get("locale") or "en-US",
        "lang_full": fp.get("accept_language") or "",
        "browser_type": fp.get("browser_type") or "",
        "platform": fp.get("navigator_platform") or "",
        "vendor": fp.get("navigator_vendor"),
        "hardware_concurrency": fp.get("hardware_concurrency") or 0,
        "device_memory": fp.get("device_memory"),
        "max_touch_points": fp.get("max_touch_points") or 0,
        "device_pixel_ratio": fp.get("device_pixel_ratio") or 0.0,
        "timezone": fp.get("timezone_id") or "UTC",
        "sec_ch_ua_full_version_list": fp.get("sec_ch_ua_full_version_list") or "",
    }


def _refresh_flow_sentinel(
    session,
    *,
    device_id: str,
    flow: str,
    fp: dict[str, Any],
    proxy_url: str | None,
    log: LogFn,
) -> tuple[str, str]:
    """QuickJS 按 flow 现算 sentinel token（v0.5.5：flow 必须匹配，否则是风控特征）。

    返回 (token, so_token)；失败返回 ("", "")，不抛异常（网络类异常由 _TlsRetrySession 兜）。
    """
    try:
        from ._sentinel_quickjs import get_sentinel_token_via_quickjs

        res = get_sentinel_token_via_quickjs(
            session,
            device_id,
            flow=flow,
            log=log,
            proxy=proxy_url,
            impersonate=fp.get("impersonate") or None,
            **_quickjs_fp_kwargs(fp),
        )
    except Exception as exc:
        import traceback as _tb

        log(f"  [QuickJS] flow={flow} sentinel 异常（沿用旧 token）: {str(exc)[:160]}")
        log("  " + _tb.format_exc().splitlines()[-4][:200])
        return "", ""
    if not res:
        log(f"  [QuickJS] flow={flow} sentinel 无结果（沿用旧 token）")
        return "", ""
    return res[0], res[1]


# ── 密码注册（吸收 v0.5.5 register_password）──────────────────────
def _register_password(
    session,
    *,
    email: str,
    password: str,
    device_id: str,
    fp: dict[str, Any],
    proxy_url: str | None,
    log: LogFn,
) -> tuple[bool, str, str]:
    """设密码。POST user/register 200 后 OpenAI 侧账号+密码已建好；失败返回 (False,..)。

    成功后服务端切流程到 email_otp_send，之前 OTP 立即失效，必须主动重发。
    返回 (ok, 刷新后的 sentinel_token, so_token) —— 主动重发 OTP 要用刷新后的 token。
    """
    bh = _browser_headers(fp, "application/json")
    # 先访问 create-account/password 页面建立服务端状态（v0.5.5 HAR 确认必需）
    try:
        session.get(
            f"{AUTH_BASE}/create-account/password",
            headers={**_browser_headers(fp, NAV_ACCEPT), "Referer": f"{AUTH_BASE}/create-account"},
            **_req_kwargs(proxy_url, fp=fp, timeout=20),
        )
    except Exception:
        pass
    # 注册前刷新 flow=username_password_create 的 sentinel（flow 必须匹配）
    token, so_token = _refresh_flow_sentinel(
        session, device_id=device_id, flow="username_password_create", fp=fp, proxy_url=proxy_url, log=log
    )
    if not token:
        return False, "", ""
    headers = {
        **bh,
        "Content-Type": "application/json",
        "Origin": AUTH_BASE,
        "Referer": f"{AUTH_BASE}/create-account/password",
    }
    headers["openai-sentinel-token"] = token
    if so_token:
        headers["openai-sentinel-so-token"] = so_token
    try:
        r = session.post(
            f"{AUTH_BASE}/api/accounts/user/register",
            json={"password": password, "username": email},
            headers=headers,
            **_req_kwargs(proxy_url, fp=fp),
        )
    except Exception as exc:
        log(f"  密码注册请求异常: {str(exc)[:160]}")
        return False, "", ""
    if r.status_code != 200:
        log(f"  密码注册失败 [{r.status_code}]: {str(r.text)[:160]}")
        return False, "", ""
    log("  密码注册成功（账号已带密码）")
    return True, token, so_token


def _send_otp(session, *, fp: dict[str, Any], proxy_url: str | None, token: str, so_token: str, log: LogFn) -> bool:
    """密码注册后主动重发 OTP（旧码已失效）。"""
    bh = _browser_headers(fp, "application/json")
    headers = {**bh, "Referer": f"{AUTH_BASE}/create-account/password"}
    if token:
        headers["openai-sentinel-token"] = token
    if so_token:
        headers["openai-sentinel-so-token"] = so_token
    try:
        r = session.get(f"{AUTH_BASE}/api/accounts/email-otp/send", headers=headers, **_req_kwargs(proxy_url, fp=fp))
        if r.status_code == 200:
            log("  OTP 已主动重发")
            return True
        log(f"  主动重发 OTP 失败 [{r.status_code}]: {str(r.text)[:120]}")
    except Exception as exc:
        log(f"  主动重发 OTP 异常: {str(exc)[:120]}")
    return False


def _resend_otp(session, *, fp: dict[str, Any], proxy_url: str | None, token: str, so_token: str) -> bool:
    """OTP 错码补发（verify 401 时用）。"""
    bh = _browser_headers(fp, "application/json")
    headers = {
        **bh,
        "Content-Type": "application/json",
        "Origin": AUTH_BASE,
        "Referer": f"{AUTH_BASE}/email-verification",
    }
    if token:
        headers["openai-sentinel-token"] = token
    if so_token:
        headers["openai-sentinel-so-token"] = so_token
    try:
        r = session.post(f"{AUTH_BASE}/api/accounts/email-otp/resend", json={}, headers=headers, **_req_kwargs(proxy_url, fp=fp))
        return r.status_code == 200
    except Exception:
        return False


def _verify_otp_once(session, *, code: str, sd: dict, fp: dict[str, Any], proxy_url: str | None) -> tuple[int, dict, str]:
    """发一次 OTP 验证。返回 (status, json, 原始 body 文本)。"""
    bh = _browser_headers(fp, "application/json")
    otp_headers = {
        **bh,
        "Origin": AUTH_BASE,
        "Referer": f"{AUTH_BASE}/email-verification",
        "Content-Type": "application/json",
    }
    if sd.get("sentinel_token"):
        otp_headers["openai-sentinel-token"] = sd["sentinel_token"]
    if sd.get("sentinel_so_token"):
        otp_headers["openai-sentinel-so-token"] = sd["sentinel_so_token"]
    r = session.post(
        f"{AUTH_BASE}/api/accounts/email-otp/validate",
        json={"code": str(code).strip()},
        headers=otp_headers,
        **_req_kwargs(proxy_url, fp=fp),
    )
    text = (r.text or "")[:240]
    try:
        data = r.json()
    except Exception:
        data = {}
    return r.status_code, data, text


def _wait_new_code(
    wait_code_sync: Callable[..., str | None],
    email: str,
    *,
    skip: set[str],
    mail_timeout: float,
    log: LogFn,
) -> str | None:
    """等一封与已知旧码不同的验证码（模拟 v0.5.5 的 issued_after 过滤）。

    密码注册切流程后旧 OTP 立即失效，但临时邮箱会一直返回旧邮件；
    借助 provider 的 skip_codes 过滤旧码，单次长轮询直到新码或超时。
    注意：不能拆成多次短轮询——provider 每次超时会 release_email 释放邮箱。
    """
    t0 = time.time()
    skip_codes = {str(c).strip() for c in skip if c}
    log(f"  等待新 OTP（跳过旧码 {len(skip_codes)} 个，最长 {mail_timeout:.0f}s）...")
    nc = wait_code_sync(email, skip_codes=skip_codes)
    if nc:
        log(f"  新 OTP 已到: {str(nc)[:2]}**** ({time.time() - t0:.1f}s)")
    else:
        log(f"  新 OTP 等待超时 ({time.time() - t0:.1f}s)")
    return nc


# ── 注册后绑定 TOTP 2FA（吸收 v0.5.5 two_factor 快路径）────────────
def _bind_totp_2fa(session, *, access_token: str, fp: dict[str, Any], proxy_url: str | None, log: LogFn) -> dict:
    """注册成功后程序化绑定 TOTP 2FA。失败返回 {}，绝不影响注册结果。

    注册链几十秒前刚做完 OTP + create_account，服务端视为"最近认证过"，
    enroll 不会 401 recent_auth_required（v0.5.5 实测 6.2s、零 PoW、零邮件）。
    """
    bh = _browser_headers(fp, "application/json")
    auth_headers = {
        **bh,
        "Authorization": f"Bearer {access_token}",
        "Origin": CHAT_BASE,
        "Referer": f"{CHAT_BASE}/settings/security",
    }
    # 1. 幂等检查：已绑 totp 则跳过（secret 取不回）
    try:
        r = session.get(f"{CHAT_BASE}/backend-api/accounts/mfa_info", headers=auth_headers, **_req_kwargs(proxy_url, fp=fp, timeout=30))
        if r.status_code == 200 and (r.json() or {}).get("mfa_enabled"):
            log("  [2FA] 该号已绑 totp，跳过")
            return {}
    except Exception as exc:
        log(f"  [2FA] mfa_info 异常: {str(exc)[:120]}")
        return {}
    # 2. enroll（secret 只在本次响应出现）
    try:
        r = session.post(
            f"{CHAT_BASE}/backend-api/accounts/mfa/enroll",
            json={"factor_type": "totp"},
            headers={**auth_headers, "Content-Type": "application/json"},
            **_req_kwargs(proxy_url, fp=fp, timeout=30),
        )
        if r.status_code != 200:
            log(f"  [2FA] enroll [{r.status_code}]: {str(r.text)[:120]}")
            return {}
        en = r.json() or {}
        secret = str(en.get("secret") or "")
        session_id = str(en.get("session_id") or "")
        if not secret or not session_id:
            log("  [2FA] enroll 缺 secret/session_id")
            return {}
    except Exception as exc:
        log(f"  [2FA] enroll 异常: {str(exc)[:120]}")
        return {}
    # 3. 算码激活
    try:
        code = _totp_now(secret)
        r = session.post(
            f"{CHAT_BASE}/backend-api/accounts/mfa/user/activate_enrollment",
            json={"code": code, "factor_type": "totp", "session_id": session_id},
            headers={**auth_headers, "Content-Type": "application/json"},
            **_req_kwargs(proxy_url, fp=fp, timeout=30),
        )
        if r.status_code != 200:
            log(f"  [2FA] activate [{r.status_code}]: {str(r.text)[:120]}（429 可等 60s 换码重试）")
            return {}
    except Exception as exc:
        log(f"  [2FA] activate 异常: {str(exc)[:120]}")
        return {}
    log("  [2FA] TOTP 绑定成功")
    return {"totp_secret": secret, "mfa_enabled": True}


def _verify_alive(session, *, access_token: str, fp: dict[str, Any], proxy_url: str | None, log: LogFn) -> None:
    """注册后立即验活：GET /backend-api/me，2xx 视为有效。

    挡掉「刚签发就被 revoke」的脏号，避免污染号池 / 拉低存活率统计。
    失败抛 RuntimeError（注册收口要求，不产出）。
    """
    headers = {
        **_browser_headers(fp, "application/json"),
        "Authorization": f"Bearer {access_token}",
        "Origin": CHAT_BASE,
        "Referer": f"{CHAT_BASE}/",
    }
    try:
        r = session.get(
            f"{CHAT_BASE}/backend-api/me",
            headers=headers,
            **_req_kwargs(proxy_url, fp=fp, timeout=30),
        )
    except Exception as exc:
        raise RuntimeError(f"验活失败（请求异常）: {str(exc)[:160]}") from exc
    if r.status_code < 200 or r.status_code >= 300:
        raise RuntimeError(f"验活失败 [{r.status_code}]: {str(r.text)[:160]}")
    log(f"  [验活] /backend-api/me {r.status_code} OK")


def _register_sync(
    *,
    email: str,
    sd: dict[str, str],
    wait_code_sync: Callable[[str], str | None],
    proxy_url: str | None,
    fp: dict[str, Any],
    fetch_refresh_token: bool,
    sentinel_refresh: bool,
    mail_timeout: float = 180,
    log: LogFn,
) -> dict[str, str]:
    curl_requests = _require_curl_cffi()
    password = _gen_password()
    fn, ln = _random_name()
    birthdate = _random_birthdate()
    # 优先复用 Sentinel 浏览器的 oai-did（authorize 风控更认）；没有再新生成
    oai_did = str(sd.get("oai_did") or "").strip() or str(uuid.uuid4())

    log(f"  密码: {password}")
    log(f"  姓名: {fn} {ln}  生日: {birthdate}")
    if proxy_url:
        log(f"  curl 代理: {proxy_url}")

    session = _TlsRetrySession(curl_requests.Session(), log=log)
    _apply_sentinel_cookies(session, sd.get("cookie_str") or "", oai_did=oai_did)

    bh = _browser_headers(fp, "application/json")

    # [2] CSRF — 必须用 /api/auth/csrf 的 csrfToken；回退 "true" 会 signin 被踢回登录页
    # 不拉 /auth/login 大 HTML：代理下常 curl(28) 半包，且 csrf API 已够用
    log("[2/9] CSRF...")
    t0 = time.time()
    try:
        r = session.get(
            f"{CHAT_BASE}/api/auth/csrf",
            headers={
                **bh,
                "Referer": f"{CHAT_BASE}/auth/login",
                "Origin": CHAT_BASE,
            },
            **_req_kwargs(proxy_url, fp=fp, timeout=45),
        )
    except Exception as exc:
        if _is_curl_timeout(exc):
            raise RetriableRegisterError(f"CSRF 请求超时: {str(exc)[:160]}") from exc
        raise RetriableRegisterError(f"CSRF 请求失败: {str(exc)[:160]}") from exc
    csrf = _csrf_from_response(r)
    if not csrf:
        raise RetriableRegisterError(f"CSRF 获取失败 status={r.status_code} body={str(r.text)[:120]}")
    log(f"  OK csrf_len={len(csrf)} ({time.time() - t0:.1f}s)")

    # [3] Initiate registration
    log("[3/9] 发起注册...")
    t0 = time.time()
    sp = {
        "prompt": "login",
        "ext-oai-did": oai_did,
        "auth_session_logging_id": str(uuid.uuid4()).replace("-", ""),
        "screen_hint": "login_or_signup",
        "login_hint": email,
    }
    r = session.post(
        f"{CHAT_BASE}/api/auth/signin/openai?" + urlencode(sp),
        data=urlencode({"csrfToken": csrf}),
        headers={
            **bh,
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": CHAT_BASE,
            "Referer": f"{CHAT_BASE}/auth/login",
            # 表单提交是导航语义（非 fetch）
            "sec-fetch-site": "same-origin",
            "sec-fetch-mode": "navigate",
            "sec-fetch-dest": "document",
        },
        allow_redirects=False,
        **_req_kwargs(proxy_url, fp=fp),
    )
    sb: dict = {}
    try:
        sb = r.json()
    except Exception:
        pass
    ru = sb.get("url") or r.headers.get("Location", "")
    if not ru:
        raise RetriableRegisterError(f"注册发起失败: {r.text[:200]}")
    # csrfToken 无效时 next-auth 会 302 到 /api/auth/signin?csrf=true
    if "csrf=true" in str(ru) or str(ru).endswith("/api/auth/signin"):
        raise RetriableRegisterError(f"CSRF 无效，signin 被打回: {str(ru)[:160]}")
    log(f"  OK ({time.time() - t0:.1f}s)")

    # [4] OAuth redirect — 必须跟随跳转，成功路径触发发 OTP
    # authorize 需带 Sentinel 头 + 多域 cookie，否则 2026-07 起常 403 CF
    # 代理慢/CF 时 30s 常 curl(28) 半包超时；authorize 单独加长
    log("[4/9] OAuth 跳转...")
    t0 = time.time()
    # 跨站导航（chatgpt.com → auth.openai.com）：真实浏览器为 cross-site/navigate
    oauth_headers = _browser_headers(fp, NAV_ACCEPT)
    oauth_headers.update(
        {
            "Origin": AUTH_BASE,
            "Referer": f"{CHAT_BASE}/",
            "upgrade-insecure-requests": "1",
            "sec-fetch-site": "cross-site",
            "sec-fetch-mode": "navigate",
            "sec-fetch-dest": "document",
        }
    )
    if sd.get("sentinel_token"):
        oauth_headers["openai-sentinel-token"] = sd["sentinel_token"]
    if sd.get("sentinel_so_token"):
        oauth_headers["openai-sentinel-so-token"] = sd["sentinel_so_token"]

    def _oauth_get(url: str, *, hop: int, timeout: float = 60):
        try:
            return session.get(
                url,
                headers=oauth_headers,
                allow_redirects=False,
                **_req_kwargs(proxy_url, fp=fp, timeout=timeout),
            )
        except Exception as exc:
            msg = str(exc)
            if "timed out" in msg.lower() or "curl: (28)" in msg or "Timeout" in type(exc).__name__:
                raise RetriableRegisterError(
                    f"OAuth hop{hop} 超时 url={(url or '')[:120]}: {msg[:160]}"
                ) from exc
            raise RetriableRegisterError(f"OAuth hop{hop} 请求失败: {msg[:160]}") from exc

    # 手动跟跳转，便于识别 authorize 403 / 落到 email-verification
    cur = ru
    r = None
    final = ""
    for hop in range(12):
        # 首跳 authorize 最关键且最慢；后续页 45s 足够
        hop_timeout = 75 if hop == 0 else 45
        r = _oauth_get(cur, hop=hop, timeout=hop_timeout)
        final = str(getattr(r, "url", cur) or cur)
        loc = r.headers.get("Location", "") or ""
        log(f"  hop{hop} status={r.status_code} path={(final or cur)[:100]} loc={(loc or '')[:80]}")
        if r.status_code >= 400:
            break
        if not loc or r.status_code < 300:
            break
        if loc.startswith("/"):
            loc = urljoin(final if final.startswith("http") else AUTH_BASE, loc)
        elif not loc.startswith("http"):
            loc = urljoin(final if final.startswith("http") else AUTH_BASE, loc)
        cur = loc
        # 已进入验证/建号页即可停；302 Location 已触发发 OTP，不必再 GET 大 HTML
        low = (cur or "").lower()
        if any(x in low for x in ("email-verification", "email-otp", "about-you", "create-account")):
            final = cur
            # 轻量 GET 落地 cookie；失败不阻断（OTP 可能已发出）
            try:
                r = _oauth_get(cur, hop=hop + 1, timeout=45)
                final = str(getattr(r, "url", cur) or cur)
            except RetriableRegisterError as exc:
                log(f"  [提示] 验证页 GET 失败（已有 Location，继续等 OTP）: {exc}")
                r = None
            break

    if "auth.openai.com" in final:
        cp = final.split("auth.openai.com")[-1]
    else:
        cp = final
    status = getattr(r, "status_code", 0) if r is not None else 0
    # 若只靠 Location 进了 email-verification，视为成功
    if any(x in (cp or "").lower() for x in ("email-verification", "email-otp", "about-you")):
        status = status or 200
    log(f"  status={status} path={cp[:120]} ({time.time() - t0:.1f}s)")
    if "/log-in" in cp and "signup" not in cp.lower() and "create-account" not in cp:
        raise RuntimeError("账号可能已存在（跳转到 log-in）")

    body_snip = ""
    try:
        body_snip = (r.text or "")[:160] if r is not None else ""
    except Exception:
        body_snip = ""
    stuck_authorize = "/api/accounts/authorize" in (cp or "") and "email-verification" not in (cp or "")
    cf_block = "just a moment" in body_snip.lower() or (
        "cf-ray" in body_snip.lower() and "email-verification" not in (cp or "").lower()
    )
    if status >= 400 or stuck_authorize or cf_block:
        raise RetriableRegisterError(
            f"OAuth 未进入验证/建号页 status={status} path={cp[:160]}"
        )
    if "email-verification" not in cp and "email-otp" not in cp:
        # chatgpt.com/auth/login 说明没真正进 authorize 成功路径
        if "chatgpt.com/auth/login" in (cp or "").lower():
            raise RetriableRegisterError(f"OAuth 回落登录页（未发 OTP）: {cp[:160]}")
        log(f"  [提示] 未直接落到 email-verification，仍按流程等 OTP: {cp[:100]}")

    # [5] Email OTP — 强制先设密码（存活优势：无密码号只能靠临时邮箱收码登录，
    #     邮箱域名失效即永久丢失；本项为注册收口的硬性不变式，不可关闭）
    log("[5/9] 邮箱验证码...")
    t0 = time.time()
    password_set = False
    first_code = wait_code_sync(email)
    if not first_code:
        # 邮箱没自动发码不一定是死路：密码注册流程本身会主动发码
        first_code = ""
    pw_ok, token, so_token = _register_password(
        session, email=email, password=password, device_id=oai_did, fp=fp, proxy_url=proxy_url, log=log
    )
    if not pw_ok:
        # 强制收口：设密码失败即注册失败，不降级为无密码 OTP，避免产出无法恢复的账号
        raise RuntimeError("设密码失败：无法保证账号可脱离邮箱恢复（注册收口要求）")
    password_set = True
    # 成功后服务端切流程，旧 OTP 立即失效；用刷新后的 flow token 主动重发
    sd["sentinel_token"] = token
    sd["sentinel_so_token"] = so_token
    if not _send_otp(session, fp=fp, proxy_url=proxy_url, token=token, so_token=so_token, log=log):
        _resend_otp(session, fp=fp, proxy_url=proxy_url, token=token, so_token=so_token)
    code = _wait_new_code(wait_code_sync, email, skip={first_code} if first_code else set(), mail_timeout=mail_timeout, log=log)
    if not code:
        raise RuntimeError("邮箱验证码获取失败（超时或未收到）")
    log(f"  验证码: {str(code)[:2]}**** ({time.time() - t0:.1f}s)")

    # [6] Validate OTP — 2026-07 起无 Sentinel 头会 403 CF（探针：plain=403, sentinel=200）
    # 401 错码：补发一次 OTP 再试（v0.5.5 verify_otp 重试）
    log("[6/9] 验证邮箱 OTP...")
    t0 = time.time()
    status, data, body = _verify_otp_once(session, code=code, sd=sd, fp=fp, proxy_url=proxy_url)
    if status == 401:
        log(f"  OTP 401 错码，补发后重试...")
        if _resend_otp(session, fp=fp, proxy_url=proxy_url, token=sd.get("sentinel_token", ""), so_token=sd.get("sentinel_so_token", "")):
            new_code = _wait_new_code(wait_code_sync, email, skip={code}, mail_timeout=mail_timeout, log=log)
            if new_code:
                code = new_code
                status, data, body = _verify_otp_once(session, code=code, sd=sd, fp=fp, proxy_url=proxy_url)
    if status != 200:
        raise RuntimeError(f"OTP 验证失败 [{status}]: {body}")
    log(f"  OK ({time.time() - t0:.1f}s)")
    continue_url = ""
    try:
        continue_url = data.get("continue_url", "") or ""
    except Exception:
        pass

    # [7] Create account
    log("[7/9] 创建账号...")
    t0 = time.time()
    if sentinel_refresh:
        # 创建前刷新 flow=oauth_create_account 的 sentinel（v0.5.5：flow 必须匹配）
        token, so_token = _refresh_flow_sentinel(
            session, device_id=oai_did, flow="oauth_create_account", fp=fp, proxy_url=proxy_url, log=log
        )
        if token:
            sd["sentinel_token"] = token
            sd["sentinel_so_token"] = so_token
    ch = {
        **bh,
        "Origin": AUTH_BASE,
        "Referer": f"{AUTH_BASE}/about-you",
        "Content-Type": "application/json",
    }
    if sd.get("sentinel_token"):
        ch["openai-sentinel-token"] = sd["sentinel_token"]
    if sd.get("sentinel_so_token"):
        ch["openai-sentinel-so-token"] = sd["sentinel_so_token"]
    r = session.post(
        f"{AUTH_BASE}/api/accounts/create_account",
        json={"name": f"{fn} {ln}", "birthdate": birthdate},
        headers=ch,
        **_req_kwargs(proxy_url, fp=fp),
    )
    if r.status_code != 200:
        raise RuntimeError(f"创建账号失败 [{r.status_code}]: {r.text[:200]}")
    log(f"  OK ({time.time() - t0:.1f}s)")
    try:
        continue_url = r.json().get("continue_url", "") or continue_url
    except Exception:
        pass

    # [8] Follow redirects + session
    log("[8/9] 建立会话...")
    t0 = time.time()
    cur = continue_url
    redir_headers = _browser_headers(fp, NAV_ACCEPT)
    redir_headers.update(
        {
            "upgrade-insecure-requests": "1",
            "sec-fetch-site": "same-origin",
            "sec-fetch-mode": "navigate",
            "sec-fetch-dest": "document",
        }
    )
    for _ in range(8):
        if not cur:
            break
        if cur.startswith("/"):
            cur = f"{CHAT_BASE}{cur}"
        r = session.get(
            cur,
            headers=redir_headers,
            allow_redirects=False,
            **_req_kwargs(proxy_url, fp=fp),
        )
        cur = r.headers.get("Location", "")

    si = None
    for _ in range(3):
        try:
            r = session.get(
                f"{CHAT_BASE}/api/auth/session",
                headers={**bh, "Accept": "application/json"},
                **_req_kwargs(proxy_url, fp=fp, timeout=15),
            )
            if r.status_code == 200:
                si = r.json()
                break
        except Exception:
            time.sleep(1)
    log(f"  OK ({time.time() - t0:.1f}s)")

    access_token = (si or {}).get("accessToken", "") or ""
    session_token = (si or {}).get("sessionToken", "") or ""
    refresh_token = ""

    if fetch_refresh_token:
        log("[8.5/9] OAuth 获取 refresh_token...")
        t0 = time.time()
        try:
            oauth_tokens = _oauth_get_tokens(
                session,
                email=email,
                oai_did=oai_did,
                fp=fp,
                proxy_url=proxy_url,
                log=log,
            )
        except Exception as exc:
            oauth_tokens = None
            log(f"  [警告] OAuth 异常: {exc}")
        if oauth_tokens:
            refresh_token = oauth_tokens.get("refresh_token", "") or ""
            if oauth_tokens.get("access_token"):
                access_token = oauth_tokens["access_token"]
            log(f"  OK refresh_token={'有' if refresh_token else '无'} ({time.time() - t0:.1f}s)")
        else:
            log(f"  [警告] 未获取 refresh_token ({time.time() - t0:.1f}s)")

    if not access_token:
        raise RuntimeError("注册流程完成但未拿到 accessToken")

    # [8.6] 强制绑定 TOTP 2FA（v0.5.5 快路径：注册会话直接 enroll，secret 只出现一次）
    # 注册收口不变式：拿到 TOTP secret 才能用「邮箱+密码+TOTP」脱离邮箱 OTP 恢复账号
    log("  [2FA] 绑定 TOTP...")
    totp = _bind_totp_2fa(session, access_token=access_token, fp=fp, proxy_url=proxy_url, log=log)
    if not (totp.get("mfa_enabled") and totp.get("totp_secret")):
        # 强制收口：绑定失败（含幂等分支拿不到 secret）即注册失败，不产出无法恢复的账号
        raise RuntimeError("绑定 TOTP 2FA 失败：无法保证账号可脱离邮箱恢复（注册收口要求）")

    # [8.7] 立即验活：auth access_token 当场校验（挡掉「刚签发就失效」的脏号）
    log("  [验活] /backend-api/me ...")
    _verify_alive(session, access_token=access_token, fp=fp, proxy_url=proxy_url, log=log)

    log(f"[9/9] 完成: {email}")
    log(
        "  last_refresh="
        + datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S +0800")
    )
    return {
        "email": email,
        "password": password if password_set else "",
        "name": f"{fn} {ln}",
        "birthdate": birthdate,
        "access_token": access_token,
        "session_token": session_token,
        "refresh_token": refresh_token,
        "totp_secret": totp.get("totp_secret", ""),
        "mfa_enabled": bool(totp.get("mfa_enabled")),
        # 从 access_token JWT 解码 chatgpt_plan_type（free/plus/pro/team）
        "plan_type": _decode_jwt_plan_type(access_token),
    }


async def register_http(
    *,
    email: str,
    wait_code: WaitCodeFn,
    proxy_info: ProxyInfo | None = None,
    sentinel_proxy_info: ProxyInfo | None = None,
    user_agent: str = "",
    browser_backend: str = "playwright",
    mail_timeout: float = 180,
    fetch_refresh_token: bool = True,
    sentinel_refresh: bool = True,
    max_attempts: int = 3,
    reacquire_proxy: Callable[[], Awaitable[ProxyInfo | None]] | None = None,
    log: LogFn | None = None,
) -> dict[str, str]:
    """执行一次 HTTP 注册。

    wait_code: async (email) -> code，由调用方绑定 ctx.email.wait_code

    authorize/403 等可恢复失败会整段重试（新 Sentinel + 新 Session）。
    reacquire_proxy: 可选回调，整段重试时换新出口（重新 acquire 代理）。
        对代理池（如 WARP 粘性 sid）应每次 acquire 换实例/出口，
        避免坏实例让 3 次重试全部重蹈覆辙。

    返回 dict: email / password / access_token / session_token / refresh_token / name
    注册收口（强制，不可关闭）：先 POST user/register 设密码（否则账号只能靠临时邮箱
        收码登录，域名失效即永久丢失）→ 绑定 TOTP 2FA → GET /backend-api/me 立即验活。
        三者任一失败即判注册失败，不产出，避免污染号池。
    sentinel_refresh=True: QuickJS 按 flow 现算 sentinel（authorize 用 playwright 提取，
        建号/设密码按 flow 现算，flow 不匹配是风控特征）
    """
    _require_curl_cffi()
    _log: LogFn = log or (lambda m: None)
    ua_override = (user_agent or "").strip() or ""
    proxy_url = _proxy_url(proxy_info)
    attempts = max(1, int(max_attempts or 1))

    # A+：探测代理出口国家/时区（同一次注册的出口 IP），用于地理联动指纹
    country, ip_tz = detect_country(proxy_url)
    _log(f"HTTP 注册开始: {email}")
    _log(f"  网络: {proxy_url or '直连'}  出口国家: {country}  tz: {ip_tz}")
    _log(f"  浏览器底座: {browser_backend or 'playwright'}")

    # 出口观测：本次注册的基础信息（每次尝试都会叠加结果后落盘）
    egress_base = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "email": email,
        "proxy": _proxy_host_for_log(proxy_url),
        "country": country,
        "ip_tz": ip_tz,
    }
    t_start = time.time()

    loop = asyncio.get_running_loop()

    def wait_code_sync(addr: str, *, skip_codes: set[str] | None = None) -> str | None:
        # 密码注册切流程后需要"跳过旧码等新码"：透传 skip_codes 给 provider，
        # 一次长轮询（mail_timeout）内过滤旧邮件，避免拆多次短轮询导致
        # provider 每次超时自动 release_email 释放邮箱。
        kwargs: dict[str, Any] = {"timeout": mail_timeout}
        if skip_codes:
            kwargs["skip_codes"] = skip_codes
        try:
            coro = wait_code(addr, **kwargs)
        except TypeError:
            coro = wait_code(addr)
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            return fut.result(timeout=max(30.0, mail_timeout + 30.0))
        except Exception as exc:
            _log(f"  收码失败: {exc}")
            return None

    last_err: Exception | None = None
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            _log(f"整段重试 {attempt}/{attempts}（新 Sentinel + 新会话 + 新指纹）...")
            await asyncio.sleep(min(8.0, 2.0 * attempt))
            # 换出口重试：坏实例不再重蹈覆辙（代理池每次 acquire 换新 sid/实例）
            if callable(reacquire_proxy):
                # 如果上次失败是 proxy_dead，传递 failure_type 让服务端重启该实例
                ft = None
                if last_err:
                    from core.step_debug import classify_failure
                    fc = classify_failure(last_err)
                    if fc == "proxy_dead":
                        ft = "proxy_dead"
                try:
                    new_info = await reacquire_proxy(failure_type=ft)
                except Exception as exc:
                    _log(f"  换出口失败: {str(exc)[:160]}")
                    new_info = None
                if new_info is not None:
                    sentinel_proxy_info = new_info
                    proxy_info = new_info
                    proxy_url = _proxy_url(new_info)
                    try:
                        country, ip_tz = detect_country(proxy_url)
                    except Exception:
                        country, ip_tz = None, None
                    egress_base = {
                        **egress_base,
                        "proxy": _proxy_host_for_log(proxy_url),
                        "country": country,
                        "ip_tz": ip_tz,
                    }
                    _log(f"  已切换出口: {_proxy_host_for_log(proxy_url)}"
                         f" 国家: {country or '?'}  tz: {ip_tz or '?'}")

        # A+：每次注册随机一套指纹（重试 = 新会话新指纹，防关联）
        fp = (
            fingerprint_from_user_ua(ua_override, country, ip_tz)
            if ua_override
            else generate_fingerprint(country, ip_tz)
        )
        _log(
            f"[1/9] 提取 Sentinel Token..."
            f" 指纹={fp['browser_type']}/{fp['impersonate']} "
            f"locale={fp['locale']} tz={fp['timezone_id']}"
        )
        # 出口观测：本次尝试使用的指纹（结果在下方各分支落盘）
        egress_rec = {
            **egress_base,
            "attempt": attempt,
            "fingerprint": f"{fp['browser_type']}/{fp['impersonate']}",
            "locale": fp["locale"],
            "timezone": fp["timezone_id"],
        }
        t0 = time.time()
        # Sentinel 模式：v8=纯 HTTP+Node V8（不开浏览器）；browser=原 Playwright；
        # auto=默认先 v8，失败自动回退浏览器（可用 CHATGPT_SENTINEL_MODE 覆盖）
        import json as _json

        sentinel_mode = (
            os.environ.get("CHATGPT_SENTINEL_MODE") or "auto"
        ).strip().lower()
        sd = None
        if sentinel_mode in ("v8", "auto") and _build_first_v8 is not None:
            try:
                vh = await asyncio.to_thread(
                    _build_first_v8,
                    proxy_url=_proxy_url(sentinel_proxy_info or proxy_info),
                    fp=fp,
                    log=_log,
                )
                token_obj = _json.loads(vh.get("openai-sentinel-token", "{}") or "{}")
                sd = {
                    "sentinel_token": vh.get("openai-sentinel-token", ""),
                    "sentinel_so_token": vh.get("openai-sentinel-so-token", ""),
                    "cookie_str": "",
                    "oai_did": str(token_obj.get("id") or uuid.uuid4()),
                }
                _log(
                    f"  [Sentinel V8] 成功（无浏览器）takes={time.time() - t0:.1f}s "
                    f"so={'有' if sd['sentinel_so_token'] else '无'}"
                )
            except Exception as exc:
                if sentinel_mode == "v8":
                    raise RetriableRegisterError(f"Sentinel V8 失败: {exc}") from exc
                _log(f"  [Sentinel V8] 失败，回退浏览器: {str(exc)[:160]}")
        if sd is None:
            try:
                sd = await extract_sentinel(
                    proxy_info=sentinel_proxy_info or proxy_info,
                    user_agent=ua_override,
                    browser_backend=browser_backend,
                    log=_log,
                    fingerprint=fp,
                )
            except Exception as exc:
                last_err = RetriableRegisterError(f"Sentinel 提取失败: {exc}")
                _log(f"  [错误] {last_err}")
                _append_egress(
                    {
                        **egress_rec,
                        "result": "retry",
                        "error": str(exc)[:200],
                        "dur_s": round(time.time() - t_start, 1),
                    }
                )
                continue
        if not sd.get("sentinel_token"):
            last_err = RetriableRegisterError("Sentinel token 为空")
            _log(f"  [错误] {last_err}")
            _append_egress(
                {**egress_rec, "result": "retry", "error": "sentinel token empty", "dur_s": round(time.time() - t_start, 1)}
            )
            continue
        _log(f"  OK ({time.time() - t0:.1f}s)")

        # 模拟人类时序：浏览器取完 token 后到 curl 发首请求之间留 1~3s
        await asyncio.sleep(random.uniform(1.0, 3.0))

        try:
            out = await asyncio.to_thread(
                _register_sync,
                email=email,
                sd=sd,
                wait_code_sync=wait_code_sync,
                proxy_url=proxy_url,
                fp=fp,
                fetch_refresh_token=fetch_refresh_token,
                sentinel_refresh=sentinel_refresh,
                mail_timeout=mail_timeout,
                log=_log,
            )
        except RetriableRegisterError as exc:
            last_err = exc
            _log(f"  [可重试失败] {exc}")
            _append_egress(
                {
                    **egress_rec,
                    "result": "retry",
                    "error": str(exc)[:200],
                    "dur_s": round(time.time() - t_start, 1),
                }
            )
            continue
        except RuntimeError as exc:
            msg = str(exc)
            # 会话/风控类错误：整段重试；OTP 超时等不重试（邮箱已消耗）
            retriable_markers = (
                "创建账号失败 [403]",
                "创建账号失败 [409]",
                "创建账号失败 [429]",
                "OTP 验证失败 [403]",
                "OTP 验证失败 [409]",
                "注册发起失败",
                "OAuth 未进入",
                "OAuth hop",
                "curl: (28)",
                "Operation timed out",
            )
            if any(m in msg for m in retriable_markers) or _is_curl_timeout(exc):
                last_err = RetriableRegisterError(msg)
                _log(f"  [可重试失败] {exc}")
                _append_egress(
                    {
                        **egress_rec,
                        "result": "retry",
                        "error": str(exc)[:200],
                        "dur_s": round(time.time() - t_start, 1),
                    }
                )
                continue
            _append_egress(
                {
                    **egress_rec,
                    "result": "fail",
                    "error": str(exc)[:200],
                    "dur_s": round(time.time() - t_start, 1),
                }
            )
            raise
        except Exception as exc:
            # curl_cffi 超时/网络错误（非 RuntimeError）也整段重试
            if _is_curl_timeout(exc) or "curl:" in str(exc):
                last_err = RetriableRegisterError(str(exc)[:240])
                _log(f"  [可重试失败] 网络/curl: {last_err}")
                _append_egress(
                    {
                        **egress_rec,
                        "result": "retry",
                        "error": str(exc)[:200],
                        "dur_s": round(time.time() - t_start, 1),
                    }
                )
                continue
            _append_egress(
                {
                    **egress_rec,
                    "result": "fail",
                    "error": str(exc)[:200],
                    "dur_s": round(time.time() - t_start, 1),
                }
            )
            raise
        else:
            # 出口观测：注册成功（指纹随账号带入 accounts.jsonl）
            out["egress_country"] = country
            out["egress_tz"] = ip_tz
            out["egress_fingerprint"] = f"{fp['browser_type']}/{fp['impersonate']}"
            _append_egress(
                {
                    **egress_rec,
                    "result": "ok",
                    "dur_s": round(time.time() - t_start, 1),
                }
            )
            return out

    _append_egress(
        {
            **egress_base,
            "result": "fail_exhausted",
            "error": str(last_err)[:200],
            "dur_s": round(time.time() - t_start, 1),
        }
    )
    raise RuntimeError(f"HTTP 注册失败（已重试 {attempts} 次）: {last_err}")
