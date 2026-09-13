"""NVIDIA 混合引擎 - 浏览器过 CF + curl_cffi 注册 + 浏览器接管 OTP/API Key

流程：
  阶段 1 (浏览器)  : 过 CF → 填邮箱 → 点 Next → 提取 key/Cookie/UA
  阶段 2 (curl_cffi): 用 key 调 /validator/register + 解 hCaptcha + POST /user/register（201）
  阶段 3 (浏览器)  : 同浏览器用新 key 跳到 profile-complete → 自动填 OTP → consent → NGC API Key

关键洞察：
  - NVIDIA 注册成功后浏览器自动跳 `/v1/profile-complete?key=<新key>` 页
  - OTP 不是直接 HTTP 端点，而是 profile-complete 页前端 JS 提交
  - 因此让浏览器接管 OTP + consent + API Key，无需逆向 OTP 端点
  - HTTP 仍负责最慢的「注册提交」一步，保留速度优势

实现要点：
  - 使用 core.browser_runner.browser_session 统一底座（playwright/patchright 由 config 决定）
  - 自带 stealth JS 注入 + 系统 Chrome + 代理认证转发器
  - 不再直接 import patchright，避免 asyncio 兼容性问题
"""
from __future__ import annotations

import asyncio
import json
import secrets
import string
import time
import urllib.request
from typing import Any
from urllib.parse import urlparse, parse_qs, parse_qsl

from core.browser_runner import browser_session, resolve_browser_backend
from core.models import ProxyInfo


HCAPTCHA_SITEKEY = "3443d8f6-da7a-4326-929f-4d7fc89ab0d1"
API_BASE = "https://accounts.nvgs.nvidia.com"


# #region debug-point A-E:stage3-network
_DEBUG_DOMAINS = {
    "accounts.nvgs.nvidia.com",
    "login.nvgs.nvidia.com",
    "login.nvidia.com",
    "static-login.nvidia.com",
    "cloudaccounts.nvidia.com",
    "api.ngc.nvidia.com",
    "build.nvidia.com",
}


def _debug_redacted_url(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    names = [name for name, _ in parse_qsl(parsed.query, keep_blank_values=True)]
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}" + (f"?keys={','.join(names)}" if names else "")


def _debug_body_shape(raw_body: str | None) -> dict[str, Any]:
    if not raw_body:
        return {"present": False}
    try:
        value = json.loads(raw_body)
        if isinstance(value, dict):
            return {"present": True, "format": "json", "keys": sorted(value.keys())}
    except Exception:
        pass
    try:
        names = sorted({name for name, _ in parse_qsl(raw_body, keep_blank_values=True)})
        if names:
            return {"present": True, "format": "form", "keys": names}
    except Exception:
        pass
    return {"present": True, "format": "opaque", "length": len(raw_body)}


def _debug_value_shape(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _debug_value_shape(item) for key, item in value.items()}
    if isinstance(value, list):
        return {"type": "list", "length": len(value), "item_type": type(value[0]).__name__ if value else None}
    return {"type": type(value).__name__, "present": value is not None}


def _debug_report(hypothesis_id: str, location: str, msg: str, data: dict[str, Any]) -> None:
    payload = json.dumps({
        "sessionId": "nvidia-pure-http",
        "runId": "pre-fix",
        "hypothesisId": hypothesis_id,
        "location": location,
        "msg": f"[DEBUG] {msg}",
        "data": data,
        "ts": int(time.time() * 1000),
    }).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(
            "http://127.0.0.1:7777/event",
            data=payload,
            headers={"Content-Type": "application/json"},
        ), timeout=1).read()
    except Exception:
        pass
# #endregion


async def _extract_verify_link(wait_link_fn, email: str, log, timeout: float = 120) -> str | None:
    """从邮件中提取验证链接（"点击邮件链接"验证模式）。

    Args:
        wait_link_fn: async fn(email, timeout) -> link_url  （由 email Provider 注入）
        email: 注册邮箱
        log: 日志函数
        timeout: 轮询超时秒数

    Returns:
        验证链接 URL 或 None
    """
    if wait_link_fn is None:
        log("[混合-3] ❌ 未提供 wait_link_fn，无法提取验证链接")
        return None
    log(f"[混合-3] 轮询邮件验证链接（超时 {timeout}s）...")
    try:
        link = await wait_link_fn(email, timeout=timeout)
    except Exception as e:
        log(f"[混合-3] ❌ 提取验证链接异常: {e}")
        return None
    if link:
        log(f"[混合-3] ✅ 提取到验证链接: {link[:80]}...")
    else:
        log("[混合-3] ❌ 邮件中未找到验证链接")
    return link


async def _browser_open_signin(
    *,
    page,
    email: str,
    log,
) -> dict[str, Any] | None:
    """阶段 1: 浏览器过 CF + 填邮箱 + 提取信息（不关闭浏览器）

    复用 _flow.py 中已验证的 step1/step2/step3，确保 CF 通过 + 模态框加载 + 跳转 NVGS。
    NVGS 页 Angular 偶发不渲染（代理慢/CF 挑战），step3 失败时重试整个流程。

    返回:
        {
            "key": str,                # NVGS 初始 key
            "client_id": str,
            "cookies": {name: value},
            "ua": str,
            "nvgs_url": str,
        }
        失败返回 None
    """
    from . import _flow

    for attempt in range(3):
        if attempt > 0:
            log(f"[混合-1] === 第 {attempt+1} 次尝试 ===")

        # step1: 打开 signin（含重试）
        log("[混合-1] step1: 打开 signin URL ...")
        ok = await _flow.step1_open_signin(page)
        if not ok:
            log("[混合-1] ❌ step1 失败（signin 模态框未加载）")
            if attempt < 2:
                await page.wait_for_timeout(3000)
                continue
            return None

        # step2: 接受 cookies
        try:
            await _flow.step2_accept_cookies(page)
        except Exception as e:
            log(f"[混合-1] step2 cookie 异常（忽略）: {e}")

        # step3: 填邮箱 + 点 Next + 等跳转 NVGS
        log(f"[混合-1] step3: 填邮箱 + 点 Next → NVGS ...")
        try:
            ok = await _flow.step3_email_next_and_continue(page, email)
        except Exception as e:
            log(f"[混合-1] step3 异常: {e}")
            ok = False
        if not ok:
            log(f"[混合-1] ❌ step3 失败（未跳转到注册表单, 第{attempt+1}次）")
            if attempt < 2:
                log("[混合-1] 等待 5s 后重试整个流程 ...")
                await page.wait_for_timeout(5000)
                continue
            return None

        nvgs_url = page.url
        log(f"[混合-1] 已到 NVGS: {nvgs_url[:80]}")

        # 提取信息
        cookies = await page.context.cookies()
        cookie_dict = {c["name"]: c["value"] for c in cookies}
        ua = await page.evaluate("() => navigator.userAgent")

        parsed = urlparse(nvgs_url)
        params = parse_qs(parsed.query)
        key = params.get("key", [None])[0]
        client_id = params.get("client_id", [None])[0]

        if not key:
            log("[混合-1] ❌ URL 中无 key 参数")
            if attempt < 2:
                await page.wait_for_timeout(3000)
                continue
            return None

        log(f"[混合-1] ✅ 提取完成: key={key[:24]}..., cookies={len(cookie_dict)}, client_id={client_id}")
        return {
            "key": key,
            "client_id": client_id or "1214762014100529152",
            "cookies": cookie_dict,
            "ua": ua,
            "nvgs_url": nvgs_url,
        }

    return None


async def _http_register(
    *,
    email: str,
    password: str,
    cf_data: dict[str, Any],
    proxy_server: str,
    solve_captcha_fn,
    log,
) -> dict[str, Any] | None:
    """阶段 2: curl_cffi 提交注册，返回 {key, cookies}（失败返回 None）"""
    from curl_cffi import requests as cc_requests

    log("[混合-2] curl_cffi 提交注册 ...")

    session = cc_requests.Session(impersonate="chrome145")
    if proxy_server:
        session.proxies = {"http": proxy_server, "https": proxy_server}

    # 设置 Cookie
    for name, value in cf_data["cookies"].items():
        try:
            session.cookies.set(name, value, domain=".nvidia.com")
        except Exception:
            pass

    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "user-agent": cf_data["ua"],
        "origin": "https://login.nvgs.nvidia.com",
        "referer": "https://login.nvgs.nvidia.com/",
        "authorization": f"Bearer {cf_data['key']}",
    }

    # 0. 代理预热（避免首次 CONNECT 走 SOCKS5 时偶发 502）
    if proxy_server:
        log(f"[混合-2] 代理预热（GET {API_BASE}/api/1/health）...")
        for warmup in range(3):
            try:
                await asyncio.to_thread(session.get, f"{API_BASE}/api/1/health", headers=headers, timeout=15)
                log("[混合-2] 代理预热成功")
                break
            except Exception as e:
                log(f"[混合-2] 代理预热失败 (第{warmup+1}次): {str(e)[:120]}")
                if warmup < 2:
                    await asyncio.sleep(3)

    # 1. 获取 validation token（代理偶发 502，最多重试 3 次）
    log("[混合-2] GET /api/1/validator/register ...")
    resp = None
    for attempt in range(3):
        if attempt > 0:
            log(f"[混合-2] GET validator/register 重试第 {attempt+1} 次 ...")
            await asyncio.sleep(3)
        try:
            resp = await asyncio.to_thread(session.get, f"{API_BASE}/api/1/validator/register", headers=headers, timeout=30)
            break
        except Exception as e:
            log(f"[混合-2] validator/register 请求异常 (第{attempt+1}次): {str(e)[:200]}")
            if attempt < 2:
                continue
            return None
    if resp is None:
        return None
    if resp.status_code != 200:
        log(f"[混合-2] ❌ validator/register HTTP {resp.status_code}: {resp.text[:200]}")
        return None
    try:
        validation_data = resp.json().get("validation", {})
    except Exception as e:
        log(f"[混合-2] ❌ validator/register 解析失败: {e}")
        return None
    log(f"[混合-2] validation keys: {list(validation_data.keys())}")

    # 2. 解 hCaptcha（CaptchaRun 偶发 SSL EOF/SYSTEM_TIMEOUT，最多重试 5 次）
    hcaptcha_token = None
    for attempt in range(5):
        log(f"[混合-2] 解 hCaptcha (第{attempt+1}次) ...")
        try:
            hcaptcha_token = await solve_captcha_fn(
                sitekey=HCAPTCHA_SITEKEY,
                page_url=cf_data["nvgs_url"],
            )
        except Exception as e:
            log(f"[混合-2] hCaptcha 异常 (第{attempt+1}次): {e}")
            hcaptcha_token = None
            if attempt < 4:
                await asyncio.sleep(5)
            continue
        if hcaptcha_token:
            break
        log(f"[混合-2] hCaptcha 未拿到 token (第{attempt+1}次)")
        if attempt < 4:
            await asyncio.sleep(5)
    if not hcaptcha_token:
        log("[混合-2] ❌ hCaptcha 5次重试后仍未拿到 token")
        return None
    log(f"[混合-2] hCaptcha token: {hcaptcha_token[:30]}...")

    # 3. 提交注册
    validation_data["response"] = hcaptcha_token
    register_data = {
        "email": email,
        "password": password,
        "confirmPassword": password,
        "validation": validation_data,
        "data_general_agreement": True,
    }
    # POST 注册（代理偶发 Connection closed，最多重试 3 次）
    resp = None
    for attempt in range(3):
        if attempt > 0:
            log(f"[混合-2] POST 重试第 {attempt+1} 次 ...")
            await asyncio.sleep(3)
        try:
            resp = await asyncio.to_thread(session.post, 
                f"{API_BASE}/api/1/frontend/oauth/user/register",
                headers=headers,
                json=register_data,
                timeout=30,
            )
            break
        except Exception as e:
            log(f"[混合-2] POST 异常 (第{attempt+1}次): {e}")
            if attempt < 2:
                continue
            return None
    if resp is None:
        return None
    log(f"[混合-2] 注册 HTTP {resp.status_code}")

    if resp.status_code != 201:
        log(f"[混合-2] ❌ 注册失败: {resp.text[:300]}")
        return None

    try:
        body = resp.json()
    except Exception:
        body = {}
    log(f"[混合-2] 注册响应 keys: {list(body.keys()) if isinstance(body, dict) else type(body).__name__}")
    new_key = body.get("key") if isinstance(body, dict) else None

    # 提取 curl_cffi session 的全部 Cookie（注册后服务器可能 set 了新 session cookie）
    resp_cookies = {}
    try:
        for c in session.cookies.jar:
            resp_cookies[c.name] = c.value
    except Exception:
        # 兜底：用 dict 形式
        resp_cookies = dict(session.cookies) if session.cookies else {}

    if new_key:
        log(f"[混合-2] ✅ 注册成功！新 key: {new_key[:24]}..., cookies: {len(resp_cookies)}")
    else:
        log(f"[混合-2] ⚠️ 响应无 key 字段，响应体: {str(body)[:300]}")
    return {"key": new_key, "cookies": resp_cookies}


async def _http_stage3_verify_email(
    *,
    email: str,
    password: str,
    cf_data: dict[str, Any],
    reg_result: dict[str, Any],
    proxy_server: str,
    wait_link_fn,
    log,
) -> dict[str, Any]:
    """阶段 3 HTTP 子流程：NGC login 获取新 key → 密码登录 → user/next → 邮件验证。

    关键：阶段 3 需要的是 LOGIN key（从 api.ngc.nvidia.com/login 发起新 OAuth 流程获取），
    不是阶段 2 的注册 key。NGC login 端点无 CF 保护，可纯 HTTP 获取。
    """
    from curl_cffi import requests as cc_requests
    from urllib.parse import urlencode as _urlencode

    if wait_link_fn is None:
        return {"ok": False, "reason": "未提供 wait_link_fn，无法执行邮件链接验证"}

    ua = cf_data.get("ua") or ""
    session = cc_requests.Session(impersonate="chrome145")
    if proxy_server:
        session.proxies = {"http": proxy_server, "https": proxy_server}
    # 注入阶段 1/2 的 cookies（NVGS 共用 .nvidia.com 域）
    cookies = {**(cf_data.get("cookies") or {}), **(reg_result.get("cookies") or {})}
    for name, value in cookies.items():
        try:
            session.cookies.set(name, value, domain=".nvidia.com")
        except Exception:
            pass

    # SOCKS5 代理偶发 TLS/连接关闭（curl 35/97），包装 session.get/post 自动重试 3 次。
    # 阶段 3a 有 30+ 个请求，逐一加重试不现实，monkey-patch 统一处理。
    _orig_get = session.get
    _orig_post = session.post

    def _retrying_get(url, *args, **kwargs):
        last_err: Exception | None = None
        for _ in range(3):
            try:
                return _orig_get(url, *args, **kwargs)
            except Exception as e:
                last_err = e
                log(f"[混合-3-HTTP] GET 重试: {str(e)[:120]}")
                time.sleep(2)
        raise last_err  # type: ignore[misc]

    def _retrying_post(url, *args, **kwargs):
        last_err: Exception | None = None
        for _ in range(3):
            try:
                return _orig_post(url, *args, **kwargs)
            except Exception as e:
                last_err = e
                log(f"[混合-3-HTTP] POST 重试: {str(e)[:120]}")
                time.sleep(2)
        raise last_err  # type: ignore[misc]

    session.get = _retrying_get  # type: ignore[assignment]
    session.post = _retrying_post  # type: ignore[assignment]

    # ── 步骤 0: NGC login 获取新 LOGIN key（不经过 build.nvidia.com，无 CF）──
    nav_headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "user-agent": ua,
    }
    _saved_cookies = {}
    _self_onboard_url = ""  # 浏览器外科手术式创建 org 时需要的 self-onboard URL
    # app=api-catalog 是浏览器实际使用的 NGC 登录入口；NGC 会据此将 redirect_uri 设为
    # api.ngc.nvidia.com/session 并生成正确的 OAuth state（app=build 会导致 state 丢失、
    # callback 返回 server_error）。
    ngc_login_url = (
        f"https://api.ngc.nvidia.com/login?"
        + _urlencode({"email": email, "app": "api-catalog", "redirect_uri": "https://build.nvidia.com/"})
    )
    log("[混合-3-HTTP] GET api.ngc.nvidia.com/login（app=api-catalog，获取新 LOGIN key）...")
    try:
        resp = await asyncio.to_thread(session.get, ngc_login_url, headers=nav_headers, allow_redirects=False, timeout=30)
        current_url = resp.headers.get("location", "")
        login_key = ""
        for _hop in range(8):
            if not current_url:
                break
            parsed = urlparse(current_url)
            q = parse_qs(parsed.query)
            if "key" in q and "error" not in (parsed.query or ""):
                login_key = q["key"][0]
                break
            resp = await asyncio.to_thread(session.get, current_url, headers=nav_headers, allow_redirects=False, timeout=30)
            loc = resp.headers.get("location", "")
            if resp.status_code not in (301, 302, 303, 307, 308) or not loc:
                break
            current_url = loc
        if not login_key:
            return {"ok": False, "reason": "NGC login 重定向链未返回 key"}
        current_key = login_key
        log(f"[混合-3-HTTP] ✅ 获取新 LOGIN key: {current_key[:24]}...")
    except Exception as e:
        return {"ok": False, "reason": f"NGC login 异常: {e}"}

    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "user-agent": ua,
        "origin": "https://login.nvgs.nvidia.com",
        "referer": "https://login.nvgs.nvidia.com/",
        "authorization": f"Bearer {current_key}",
    }

    try:
        device_id = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))

        # 1. initialize/check（NVGS 流程必须先初始化，否则后续 login/password 返回 OPERATION_INVALID）
        log("[混合-3-HTTP] POST /initialize/check ...")
        resp = await asyncio.to_thread(session.post, 
            f"{API_BASE}/api/1/frontend/oauth/initialize/check",
            headers=headers,
            json={"browserMode": "Normal", "passkeySupported": False},
            timeout=30,
        )
        if resp.status_code != 200:
            return {
                "ok": False,
                "reason": f"NVGS initialize/check HTTP {resp.status_code}: {resp.text[:200]}",
                "key": current_key,
            }

        # 2. account/check（提交 deviceId + email，NVGS 据此判断账号是否已注册）
        log("[混合-3-HTTP] POST /account/check ...")
        resp = await asyncio.to_thread(session.post, 
            f"{API_BASE}/api/1/frontend/oauth/account/check",
            headers=headers,
            json={"deviceId": device_id, "email": email, "rememberLogin": True},
            timeout=30,
        )
        if resp.status_code != 200:
            return {
                "ok": False,
                "reason": f"NVGS account/check HTTP {resp.status_code}: {resp.text[:200]}",
                "key": current_key,
            }

        # 3. user/login/password（密码登录，返回新 key）
        log("[混合-3-HTTP] POST /user/login/password ...")
        resp = await asyncio.to_thread(session.post, 
            f"{API_BASE}/api/1/frontend/oauth/user/login/password",
            headers=headers,
            json={"deviceId": device_id, "password": password, "rememberLogin": True},
            timeout=30,
        )
        if resp.status_code != 201:
            return {
                "ok": False,
                "reason": f"NVGS 密码登录 HTTP {resp.status_code}: {resp.text[:200]}",
                "key": current_key,
            }
        try:
            body = resp.json()
        except Exception:
            body = {}
        if isinstance(body, dict) and body.get("key"):
            current_key = body["key"]
            headers["authorization"] = f"Bearer {current_key}"

        log("[混合-3-HTTP] POST /user/next ...")
        # user/next 是状态机：可能返回 RememberLogIn（记住设备）等中间步骤，
        # 需要循环调用直到到达 EmailVerification / Consent / Finish 等目标步骤。
        for _next_attempt in range(6):
            resp = await asyncio.to_thread(session.post, 
                f"{API_BASE}/api/1/frontend/oauth/user/next",
                headers=headers,
                json={},
                timeout=30,
            )
            if resp.status_code != 200:
                return {
                    "ok": False,
                    "reason": f"NVGS user/next HTTP {resp.status_code}: {resp.text[:200]}",
                    "key": current_key,
                }
            try:
                body = resp.json()
            except Exception:
                body = {}
            if isinstance(body, dict):
                _next_step = body.get("step", "")
                log(f"[混合-3-HTTP] user/next 响应: step={_next_step} page={body.get('page','')} has_key={bool(body.get('key'))} has_ext={bool(body.get('externalUrl'))}")
                if body.get("key"):
                    current_key = body["key"]
                    headers["authorization"] = f"Bearer {current_key}"
                # RememberLogIn 是"记住设备"中间步骤，需要继续推进
                if _next_step == "RememberLogIn":
                    log("[混合-3-HTTP] RememberLogIn 步骤，继续推进 ...")
                    continue
                break
            else:
                break

        verify_link = await _extract_verify_link(wait_link_fn, email, log, timeout=120)
        if not verify_link:
            return {"ok": False, "reason": "邮件中未找到验证链接", "key": current_key}
        parsed = urlparse(verify_link)
        if parsed.hostname != "login.nvgs.nvidia.com" or parsed.path != "/profile-management/verify-email":
            return {"ok": False, "reason": "邮件验证链接不是预期的 NVGS verify-email 地址", "key": current_key}
        params = parse_qs(parsed.query)
        verify_token = (params.get("token") or params.get("code") or [""])[0]
        if not verify_token:
            return {"ok": False, "reason": "NVGS 邮件验证链接缺少 token/code", "key": current_key}
        # 邮件正文可能用 quoted-printable 编码，= 被编码为 =3D，导致 URL 中 code=3DeyJ...
        # （正确应为 code=eyJ...）。还原所有 =3D → =，再剥离开头的 3D（原 = 分隔符被编码后
        # 被 parse_qs 消费，留下 3D 前缀）。
        if "3D" in verify_token:
            log(f"[混合-3-HTTP] 检测到 quoted-printable 残留，修复前 verify_token 前 40: {verify_token[:40]}")
            verify_token = verify_token.replace("=3D", "=")
            if verify_token.startswith("3D"):
                verify_token = verify_token[2:]
            log(f"[混合-3-HTTP] 修复后 verify_token 前 40: {verify_token[:40]}")

        log("[混合-3-HTTP] POST /profile/user/email/verify ...")
        verify_headers = {
            **headers,
            "referer": verify_link,
            "referrer-id": "profile-management/verify-email",
        }
        resp = await asyncio.to_thread(session.post, 
            f"{API_BASE}/api/1/profile/user/email/verify",
            headers=verify_headers,
            json={"token": verify_token},
            timeout=30,
        )
        if resp.status_code != 200:
            return {
                "ok": False,
                "reason": f"NVGS 邮件验证 HTTP {resp.status_code}: {resp.text[:200]}",
                "key": current_key,
            }

        # GET verify-email URL（模拟浏览器导航）：浏览器是直接导航到 verify-email URL，
        # 服务器通过 save-login → profile-complete 重定向链完成验证并保持 OAuth session。
        # 单独 POST profile API 不推进 OAuth 状态机，会导致 user/next 返回 PromptPassword。
        log("[混合-3-HTTP] GET verify-email URL（跟随重定向，模拟浏览器导航）...")
        try:
            resp = await asyncio.to_thread(session.get, 
                verify_link,
                headers={**nav_headers, "referer": "https://login.nvgs.nvidia.com/"},
                allow_redirects=True,
                timeout=30,
            )
            log(f"[混合-3-HTTP] verify-email 导航完成: HTTP {resp.status_code}, URL={str(resp.url)[:80]}")
        except Exception as e:
            log(f"[混合-3-HTTP] verify-email 导航异常（忽略）: {e}")

        response_cookies = {}
        try:
            for cookie in session.cookies.jar:
                response_cookies[cookie.name] = cookie.value
        except Exception:
            response_cookies = dict(session.cookies) if session.cookies else {}

        # ── 步骤 7: 邮件验证后循环推进 user/next → consent ──
        # user/next 是状态机，邮件验证后可能返回：
        #   - PromptPassword → 邮件验证重置了 OAuth session，需要重新提交密码
        #   - RememberLogIn → "记住设备"中间步骤，继续推进
        #   - externalUrl(consent/authorize/callback) → 跟随到 consent 页
        #   - Consent/Finish → 已到目标步骤
        consent_url = ""
        log("[混合-3-HTTP] 邮件验证后循环 POST /user/next（推进到 consent）...")
        for _post_verify_attempt in range(6):
            resp = await asyncio.to_thread(session.post, 
                f"{API_BASE}/api/1/frontend/oauth/user/next",
                headers=headers,
                json={},
                timeout=30,
            )
            next_info = {}
            try:
                next_info = resp.json() if resp.status_code == 200 else {}
            except Exception:
                pass
            if not isinstance(next_info, dict):
                break
            _step = next_info.get("step", "")
            log(f"[混合-3-HTTP] user/next 响应: step={_step} page={next_info.get('page','')} externalUrl={'有' if next_info.get('externalUrl') else '无'} keys={sorted(next_info.keys())}")
            if next_info.get("key"):
                current_key = next_info["key"]
                headers["authorization"] = f"Bearer {current_key}"

            # PromptPassword: 邮件验证后 NVGS 要求重新认证。PromptPassword 返回的 key
            # 不能直接用于 account/check（会 OPERATION_INVALID）。需要发起全新 NGC login
            # 创建新 OAuth 流程，再走完整登录序列（邮件已验证 → 应直接到 consent）。
            if _step == "PromptPassword":
                log("[混合-3-HTTP] PromptPassword 步骤，发起全新 NGC login ...")
                # 1. 全新 NGC login → 获取新 OAuth key
                try:
                    resp = await asyncio.to_thread(session.get, ngc_login_url, headers=nav_headers, allow_redirects=False, timeout=30)
                    _ngc_url = resp.headers.get("location", "")
                    for _hop in range(8):
                        if not _ngc_url:
                            break
                        _p = urlparse(_ngc_url)
                        _q = parse_qs(_p.query)
                        if "key" in _q and "error" not in (_p.query or ""):
                            current_key = _q["key"][0]
                            break
                        resp = await asyncio.to_thread(session.get, _ngc_url, headers=nav_headers, allow_redirects=False, timeout=30)
                        _loc = resp.headers.get("location", "")
                        if resp.status_code not in (301, 302, 303, 307, 308) or not _loc:
                            break
                        _ngc_url = _loc
                    headers["authorization"] = f"Bearer {current_key}"
                    log(f"[混合-3-HTTP] 全新 NGC login key: {current_key[:24]}...")
                except Exception as e:
                    log(f"[混合-3-HTTP] 全新 NGC login 异常: {e}")
                    continue
                # 2. initialize/check
                resp = await asyncio.to_thread(session.post, 
                    f"{API_BASE}/api/1/frontend/oauth/initialize/check",
                    headers=headers,
                    json={"browserMode": "Normal", "passkeySupported": False},
                    timeout=30,
                )
                log(f"[混合-3-HTTP] initialize/check → HTTP {resp.status_code}")
                if resp.status_code != 200:
                    log(f"[混合-3-HTTP] initialize/check 失败: {resp.text[:200]}")
                    continue
                # 3. account/check
                resp = await asyncio.to_thread(session.post, 
                    f"{API_BASE}/api/1/frontend/oauth/account/check",
                    headers=headers,
                    json={"deviceId": device_id, "email": email, "rememberLogin": True},
                    timeout=30,
                )
                log(f"[混合-3-HTTP] account/check → HTTP {resp.status_code}")
                if resp.status_code != 200:
                    log(f"[混合-3-HTTP] account/check 失败: {resp.text[:200]}")
                    continue
                # 4. user/login/password
                resp = await asyncio.to_thread(session.post, 
                    f"{API_BASE}/api/1/frontend/oauth/user/login/password",
                    headers=headers,
                    json={"deviceId": device_id, "password": password, "rememberLogin": True},
                    timeout=30,
                )
                log(f"[混合-3-HTTP] user/login/password → HTTP {resp.status_code}")
                if resp.status_code == 201:
                    try:
                        _body = resp.json()
                        if isinstance(_body, dict) and _body.get("key"):
                            current_key = _body["key"]
                            headers["authorization"] = f"Bearer {current_key}"
                    except Exception:
                        pass
                    log("[混合-3-HTTP] 重新登录成功，继续推进 user/next ...")
                else:
                    log(f"[混合-3-HTTP] 重新登录失败 HTTP {resp.status_code}: {resp.text[:200]}")
                continue

            # RememberLogIn: "记住设备"中间步骤，继续推进
            if _step == "RememberLogIn":
                log("[混合-3-HTTP] RememberLogIn 步骤，继续推进 ...")
                continue

            # externalUrl → 跟随到 consent
            ext_url = next_info.get("externalUrl") or ""
            if ext_url and ("consent" in ext_url or "authorize" in ext_url or "callback" in ext_url):
                log(f"[混合-3-HTTP] user/next 返回 externalUrl，跟随到 consent...")
                try:
                    resp = await asyncio.to_thread(session.get, ext_url, headers=nav_headers, allow_redirects=False, timeout=30)
                    current_url = resp.headers.get("location", "")
                    for _hop in range(10):
                        if not current_url:
                            break
                        if "consent" in current_url:
                            consent_url = current_url
                            break
                        if urlparse(current_url).hostname == "build.nvidia.com" and "modal=signin" not in current_url:
                            break
                        resp = await asyncio.to_thread(session.get, current_url, headers=nav_headers, allow_redirects=False, timeout=30)
                        loc = resp.headers.get("location", "")
                        if resp.status_code not in (301, 302, 303, 307, 308) or not loc:
                            if "consent" in current_url or ("callback/consent" in (resp.text or "")[:3000]):
                                consent_url = current_url
                            break
                        current_url = loc
                except Exception as e:
                    log(f"[混合-3-HTTP] externalUrl 跟随异常: {e}")
            break

        # ── 步骤 8: 如果步骤 7 未到 consent，重新发起 NGC login → 已登录状态下应到 consent ──
        if not consent_url:
            log("[混合-3-HTTP] 重新 GET api.ngc.nvidia.com/login（已登录，跳 consent）...")
            for _retry in range(3):
                try:
                    resp = await asyncio.to_thread(session.get, ngc_login_url, headers=nav_headers, allow_redirects=False, timeout=30)
                    current_url = resp.headers.get("location", "")
                    for _hop in range(10):
                        if not current_url:
                            break
                        if "consent" in current_url:
                            consent_url = current_url
                            break
                        if urlparse(current_url).hostname == "build.nvidia.com" and "modal=signin" not in current_url:
                            log("[混合-3-HTTP] ✅ 已 consent，直接到 build.nvidia.com")
                            break
                        resp = await asyncio.to_thread(session.get, current_url, headers=nav_headers, allow_redirects=False, timeout=30)
                        loc = resp.headers.get("location", "")
                        if resp.status_code not in (301, 302, 303, 307, 308) or not loc:
                            if "consent" in current_url or ("callback/consent" in (resp.text or "")[:3000]):
                                consent_url = current_url
                            break
                        current_url = loc
                    if consent_url or (current_url and urlparse(current_url).hostname == "build.nvidia.com"):
                        break
                except Exception as e:
                    if _retry < 2:
                        log(f"[混合-3-HTTP] NGC login 重试 ({_retry+1}/3): {e}")
                        await asyncio.sleep(2)
                    else:
                        raise

        # ── 步骤 9: 提交 consent 表单 ──
        if consent_url:
            log(f"[混合-3-HTTP] 到达 consent 页: {consent_url[:80]}...")
            # GET consent 页获取 HTML（resp 可能是重定向响应，非 consent 页内容）
            try:
                resp = await asyncio.to_thread(session.get, consent_url, headers=nav_headers, timeout=30)
            except Exception as e:
                log(f"[混合-3-HTTP] consent 页 GET 异常: {e}")
                resp = None
            consent_html = (resp.text if resp else "") or ""
            import re as _re
            # 从 consent URL query 参数提取 state（consent 页 URL 含 state 参数）
            consent_parsed = urlparse(consent_url)
            consent_qs = parse_qs(consent_parsed.query)
            form_fields = {}
            # state 从 URL 提取（HTML 表单中可能没有）
            if consent_qs.get("state"):
                form_fields["state"] = consent_qs["state"][0]
            # 从 HTML 提取表单隐藏字段（双向匹配 name/value 顺序）
            for m in _re.finditer(
                r'<input[^>]+name=["\']([^"\']+)["\'][^>]*value=["\']([^"\']*)["\']',
                consent_html,
            ):
                form_fields[m.group(1)] = m.group(2)
            for m in _re.finditer(
                r'<input[^>]+value=["\']([^"\']*)["\'][^>]*name=["\']([^"\']+)["\']',
                consent_html,
            ):
                form_fields[m.group(2)] = m.group(1)
            # 也检查 action URL
            action_match = _re.search(r'<form[^>]+action=["\']([^"\']+)["\']', consent_html)
            consent_action = action_match.group(1) if action_match else "https://login.nvidia.com/callback/consent"
            if not consent_action.startswith("http"):
                consent_action = "https://login.nvidia.com" + consent_action

            # 确保 opt_in 和 trackBehavioralData 有值
            form_fields.setdefault("opt_in", "true")
            form_fields.setdefault("trackBehavioralData", "false")
            log(f"[混合-3-HTTP] POST consent（fields: {sorted(form_fields.keys())}）...")
            resp = await asyncio.to_thread(session.post, 
                consent_action,
                headers={**nav_headers, "content-type": "application/x-www-form-urlencoded", "referer": consent_url},
                data=form_fields,
                allow_redirects=False,
                timeout=30,
            )
            log(f"[混合-3-HTTP] consent 响应 HTTP {resp.status_code}")
            # 跟随重定向链到 NGC session / build.nvidia.com
            current_url = resp.headers.get("location", "")
            for _hop in range(10):
                if not current_url:
                    break
                log(f"[混合-3-HTTP] consent 重定向 hop {_hop}: {current_url[:100]}")
                if urlparse(current_url).hostname == "build.nvidia.com" and "modal=signin" not in current_url:
                    log("[混合-3-HTTP] ✅ consent 后到 build.nvidia.com")
                    break
                if "nca_picker" in current_url or "select-account" in current_url or "cloudaccounts" in current_url:
                    # 处理 NCA picker
                    log("[混合-3-HTTP] 检测到 NCA picker，提交...")
                    nca_html = (await asyncio.to_thread(session.get, current_url, headers=nav_headers, timeout=30)).text or ""
                    nca_fields = {}
                    for m in _re.finditer(
                        r'<input[^>]+name=["\']([^"\']+)["\'][^>]*value=["\']([^"\']*)["\']',
                        nca_html,
                    ):
                        nca_fields[m.group(1)] = m.group(2)
                    for m in _re.finditer(
                        r'<input[^>]+value=["\']([^"\']*)["\'][^>]*name=["\']([^"\']+)["\']',
                        nca_html,
                    ):
                        nca_fields[m.group(2)] = m.group(1)
                    nca_fields.setdefault("action", "create")
                    nca_fields.setdefault("name", email.split("@")[0])
                    resp = await asyncio.to_thread(session.post, 
                        "https://login.nvidia.com/callback/nca_picker",
                        headers={**nav_headers, "content-type": "application/x-www-form-urlencoded"},
                        data=nca_fields,
                        allow_redirects=False,
                        timeout=30,
                    )
                    current_url = resp.headers.get("location", "")
                    continue
                # self-onboard GET 会 302 → authorize → login，跟随会丢失 NGC session
                if "self-onboard" in current_url:
                    log("[混合-3-HTTP] self-onboard GET → 跟随 OAuth 重定向链（稍后恢复 session）...")
                    # 保存当前 cookies（self-onboard 重定向链会丢失 session）
                    _saved_cookies = {}
                    try:
                        for c in session.cookies.jar:
                            _saved_cookies[(c.name, c.domain)] = c.value
                    except Exception:
                        _saved_cookies = {}
                # api.ngc.nvidia.com 上的 /session、/self-onboard 是 OAuth 导航端点，
                # 用 code/state 交换 session，不能带 Bearer token（会干扰 code 交换）
                hop_headers = nav_headers
                _is_nav_endpoint = "/session" in current_url or "self-onboard" in current_url
                if "api.ngc.nvidia.com" in current_url and current_key and not _is_nav_endpoint:
                    hop_headers = {**nav_headers, "authorization": f"Bearer {current_key}"}
                resp = await asyncio.to_thread(session.get, current_url, headers=hop_headers, allow_redirects=False, timeout=30)
                loc = resp.headers.get("location", "")
                # 诊断：self-onboard / session 响应
                if "self-onboard" in current_url or "ngc.nvidia.com/session" in current_url:
                    _sc = resp.headers.get("set-cookie", "")
                    _sc_names = sorted({p.split("=")[0].strip() for p in _sc.split(";") if "=" in p and p.strip() and not p.strip().startswith(("Path", "Domain", "Expires", "Max-Age", "Secure", "HttpOnly", "SameSite"))}) if _sc else []
                    log(f"[混合-3-HTTP] {current_url[:60]} → HTTP {resp.status_code} Location={loc[:80] if loc else '(无)'} Set-Cookie={_sc_names if _sc_names else '无'}")
                # session 端点返回 Set-Cookie = NGC session 已建立。
                # self-onboard GET 会 302 → authorize → login，覆盖 session cookie，
                # 导致后续 user-context 401。因此在 session Set-Cookie 后：
                # 1. 保存 session cookies
                # 2. GET self-onboard（allow_redirects=True 跟随完整链，可能触发 org 创建）
                # 3. 恢复 session cookies
                if "ngc.nvidia.com/session" in current_url and resp.headers.get("set-cookie"):
                    log("[混合-3-HTTP] ✅ session Set-Cookie 已获取，NGC session 已建立")
                    _self_onboard_url = loc  # session 返回的 Location 是 self-onboard URL
                    if _self_onboard_url and "self-onboard" in _self_onboard_url:
                        _session_cookies = {}
                        try:
                            for c in session.cookies.jar:
                                _session_cookies[(c.name, c.domain)] = c.value
                        except Exception:
                            _session_cookies = {}
                        try:
                            so_resp = await asyncio.to_thread(session.get, _self_onboard_url, headers=nav_headers, allow_redirects=True, timeout=30)
                            log(f"[混合-3-HTTP] self-onboard GET（跟随重定向）→ HTTP {so_resp.status_code}, URL={str(so_resp.url)[:80]}")
                            # 捕获最终页 HTML，查找自动提交表单或 meta refresh
                            _final_html = (so_resp.text or "")[:2000]
                            import re as _re_mod
                            _meta_refresh = _re_mod.search(r'<meta[^>]+http-equiv=["\']?refresh["\']?[^>]+content=["\'][^"\']*url=([^"\'>\s]+)', _final_html, flags=_re_mod.I)
                            _form_action = _re_mod.search(r'<form[^>]+action=["\']([^"\']+)["\']', _final_html, flags=_re_mod.I)
                            _js_redirect = _re_mod.search(r'(?:window\.location|location\.href)\s*=\s*["\']([^"\']+)["\']', _final_html, flags=_re_mod.I)
                            if _meta_refresh:
                                log(f"[混合-3-HTTP] 最终页 meta refresh URL: {_meta_refresh.group(1)[:100]}")
                            if _form_action:
                                log(f"[混合-3-HTTP] 最终页 form action: {_form_action.group(1)[:100]}")
                            if _js_redirect:
                                log(f"[混合-3-HTTP] 最终页 JS redirect: {_js_redirect.group(1)[:100]}")
                            if not (_meta_refresh or _form_action or _js_redirect):
                                log(f"[混合-3-HTTP] 最终页前 500 字符: {_final_html[:500]}")
                        except Exception as e:
                            log(f"[混合-3-HTTP] self-onboard GET 异常: {e}")
                        for (cname, cdomain), cvalue in _session_cookies.items():
                            try:
                                session.cookies.set(cname, cvalue, domain=cdomain)
                            except Exception:
                                pass
                        log("[混合-3-HTTP] session cookies 已恢复")

                        # ★ 关键：GET select-account 页面（浏览器流程中 org 创建的触发点）
                        # 浏览器流程：consent → select-account（填 name + Create）→ build.nvidia.com → API Key
                        # HTTP 流程之前跳过了 select-account，导致 org 没创建，user-context 返回 {}
                        select_account_url = "https://cloudaccounts.nvidia.com/sf/v2/select-account?redirect_uri=https://login.nvidia.com/"
                        log("[混合-3-HTTP] GET select-account 页面（创建云账户）...")
                        try:
                            sa_resp = await asyncio.to_thread(session.get, select_account_url, headers=nav_headers, allow_redirects=True, timeout=30)
                            log(f"[混合-3-HTTP] select-account → HTTP {sa_resp.status_code}, URL={str(sa_resp.url)[:80]}")
                            sa_html = (sa_resp.text or "")
                            import re as _re_sa
                            _sa_form = _re_sa.search(r'<form[^>]+action=["\']([^"\']+)["\']', sa_html, flags=_re_sa.I)
                            _sa_name_input = _re_sa.search(r'<input[^>]+name=["\']name["\']', sa_html, flags=_re_sa.I)
                            _sa_hidden = _re_sa.findall(r'<input[^>]+type=["\']hidden["\'][^>]+name=["\']([^"\']+)["\'][^>]*value=["\']([^"\']*)["\']', sa_html, flags=_re_sa.I)
                            log(f"[混合-3-HTTP] select-account HTML: form={bool(_sa_form)}, name_input={bool(_sa_name_input)}, hidden_fields={len(_sa_hidden)}, len={len(sa_html)}")
                            if _sa_form:
                                log(f"[混合-3-HTTP] select-account form action: {_sa_form.group(1)[:100]}")
                            if _sa_hidden:
                                log(f"[混合-3-HTTP] select-account hidden fields: {[n for n,_ in _sa_hidden]}")
                            # 打印前 800 字符用于分析
                            log(f"[混合-3-HTTP] select-account 前 800 字符: {sa_html[:800]}")

                            # 如果有表单，尝试提交创建云账户
                            if _sa_form or _sa_name_input:
                                sa_action = _sa_form.group(1) if _sa_form else "https://cloudaccounts.nvidia.com/sf/v2/select-account"
                                if not sa_action.startswith("http"):
                                    sa_action = "https://cloudaccounts.nvidia.com" + sa_action
                                sa_fields = {}
                                for name, value in _sa_hidden:
                                    sa_fields[name] = value
                                sa_fields.setdefault("name", email.split("@")[0])
                                sa_fields.setdefault("action", "create")
                                log(f"[混合-3-HTTP] POST select-account（fields: {sorted(sa_fields.keys())}）...")
                                sa_post_resp = await asyncio.to_thread(session.post, 
                                    sa_action,
                                    headers={**nav_headers, "content-type": "application/x-www-form-urlencoded", "referer": select_account_url},
                                    data=sa_fields,
                                    allow_redirects=True,
                                    timeout=30,
                                )
                                _sa_post_url = str(sa_post_resp.url)
                                log(f"[混合-3-HTTP] select-account POST → HTTP {sa_post_resp.status_code}, URL={_sa_post_url[:80]}")
                                log(f"[混合-3-HTTP] select-account POST 前 500 字符: {(sa_post_resp.text or '')[:500]}")
                        except Exception as e:
                            log(f"[混合-3-HTTP] select-account GET/POST 异常: {e}")
                    break
                if resp.status_code not in (301, 302, 303, 307, 308) or not loc:
                    # 非重定向页，可能是 NCA picker 或其他页面
                    if "select-account" in current_url or "cloudaccounts" in current_url:
                        log("[混合-3-HTTP] 检测到 NCA picker 页（非重定向），提交...")
                        nca_fields = {}
                        for m in _re.finditer(
                            r'<input[^>]+name=["\']([^"\']+)["\'][^>]*value=["\']([^"\']*)["\']',
                            resp.text or "",
                        ):
                            nca_fields[m.group(1)] = m.group(2)
                        nca_fields.setdefault("action", "create")
                        nca_fields.setdefault("name", email.split("@")[0])
                        resp = await asyncio.to_thread(session.post, 
                            "https://login.nvidia.com/callback/nca_picker",
                            headers={**nav_headers, "content-type": "application/x-www-form-urlencoded"},
                            data=nca_fields,
                            allow_redirects=False,
                            timeout=30,
                        )
                        current_url = resp.headers.get("location", "")
                        continue
                    break
                current_url = loc
        else:
            log("[混合-3-HTTP] ⚠️ 未到达 consent 页，尝试直接获取 API Key...")

        # ── 步骤 9.5: 恢复 session + 重新调 user/next，跟随 self-onboard OAuth 回调 ──
        # 仅当走了 self-onboard（_saved_cookies 非空）时才需要恢复 session。
        # session 端点 Set-Cookie 后直接停止的情况：_saved_cookies 为空，跳过本步，
        #   避免 NGC login 覆盖已建立的 session cookie。
        if current_key and _saved_cookies:
            # 恢复保存的 cookies
            if _saved_cookies:
                log(f"[混合-3-HTTP] 恢复 {len(_saved_cookies)} 个 cookies...")
                for (cname, cdomain), cvalue in _saved_cookies.items():
                    try:
                        session.cookies.set(cname, cvalue, domain=cdomain)
                    except Exception:
                        pass
            # 重新调 NGC login 恢复 NGC session
            log("[混合-3-HTTP] 重新调 NGC login 恢复 session...")
            try:
                lr = await asyncio.to_thread(session.get, ngc_login_url, headers=nav_headers, allow_redirects=False, timeout=30)
                lc = lr.headers.get("location", "")
                for _lh in range(8):
                    if not lc or urlparse(lc).hostname == "build.nvidia.com":
                        break
                    lr = await asyncio.to_thread(session.get, lc, headers=nav_headers, allow_redirects=False, timeout=30)
                    lc = lr.headers.get("location", "")
                log("[混合-3-HTTP] NGC login 恢复完成")
            except Exception as e:
                log(f"[混合-3-HTTP] NGC login 恢复异常: {e}")
            # 重新调 user/next
            log("[混合-3-HTTP] consent 后重新调 user/next（跟随 self-onboard 回调）...")
            try:
                resp = await asyncio.to_thread(session.post, 
                    f"{API_BASE}/api/1/frontend/oauth/user/next",
                    headers=headers,
                    json={},
                    allow_redirects=False,
                    timeout=30,
                )
                log(f"[混合-3-HTTP] user/next (post-consent) HTTP {resp.status_code}: {resp.text[:300]}")
                if resp.status_code == 200:
                    try:
                        post_next = resp.json()
                    except Exception:
                        post_next = {}
                    if post_next.get("key"):
                        current_key = post_next["key"]
                        headers["authorization"] = f"Bearer {current_key}"
                    ext_url = post_next.get("externalUrl") or ""
                    if ext_url:
                        log(f"[混合-3-HTTP] user/next (post-consent) externalUrl: {ext_url[:120]}")
                        current_url = ext_url
                        for _hop in range(15):
                            if not current_url:
                                break
                            parsed_h = urlparse(current_url)
                            # 到达 build.nvidia.com = NGC session 已建立
                            if parsed_h.hostname == "build.nvidia.com":
                                log("[混合-3-HTTP] ✅ post-consent 到达 build.nvidia.com（NGC session 应已建立）")
                                break
                            # api.ngc.nvidia.com/session 是 OAuth code 交换端点：
                            # 它通过 code 换取并 Set-Cookie NGC session，不能用 Bearer token
                            hop_headers = nav_headers
                            if "api.ngc.nvidia.com" in current_url and current_key and "/session" not in current_url:
                                hop_headers = {**nav_headers, "authorization": f"Bearer {current_key}"}
                            resp = await asyncio.to_thread(session.get, current_url, headers=hop_headers, allow_redirects=False, timeout=30)
                            loc = resp.headers.get("location", "")
                            # 诊断 session / callback 响应
                            if "/session" in current_url or "callback/redirect" in current_url:
                                _sc = resp.headers.get("set-cookie", "")
                                log(f"[混合-3-HTTP] post-consent hop {_hop} {parsed_h.hostname}{parsed_h.path}: HTTP {resp.status_code} Location={(loc or '(无)')[:90]} Set-Cookie={'有' if _sc else '无'}")
                            else:
                                log(f"[混合-3-HTTP] post-consent hop {_hop}: HTTP {resp.status_code} Location={loc[:80] if loc else '(无)'}")
                            if resp.status_code not in (301, 302, 303, 307, 308) or not loc:
                                break
                            current_url = loc
                    else:
                        log(f"[混合-3-HTTP] user/next (post-consent) 无 externalUrl, step={post_next.get('step','')} page={post_next.get('page','')}")
            except Exception as e:
                log(f"[混合-3-HTTP] user/next (post-consent) 异常: {e}")

        # ── 步骤 10: GET /user-context → orgName ──
        # 诊断：打印 user-context 前的所有 cookies（name + domain），确认 NGC session 是否建立
        try:
            cookie_diag = [(c.name, c.domain, (c.value or "")[:16]) for c in session.cookies.jar]
            log(f"[混合-3-HTTP] user-context 前 cookies ({len(cookie_diag)}): {cookie_diag}")
        except Exception as _e:
            log(f"[混合-3-HTTP] cookie 诊断异常: {_e}")
        ngc_headers = {
            "accept": "application/json, text/plain, */*",
            "user-agent": ua,
        }
        # org 创建可能异步，带重试查 user-context。
        # 注意：HTTP 已知无法创建 org（select-account 是 Next.js SPA），
        # 仅检查 2 次，失败后直接进入浏览器外科手术式回退。
        # curl_cffi 在 SOCKS5 上偶发挂起不超时，用 asyncio.wait_for 包裹硬超时。
        org_name = ""
        _org_create_tried = False
        for _uc_retry in range(2):
            if _uc_retry > 0:
                # 尝试多种方式触发 org 创建（仅一次）
                if not _org_create_tried and current_key:
                    _org_create_tried = True
                    so_headers = {**ngc_headers, "authorization": f"Bearer {current_key}", "content-type": "application/json"}
                    # 1. PUT /self-onboard
                    log("[混合-3-HTTP] 尝试 PUT /self-onboard ...")
                    try:
                        so_resp = await asyncio.wait_for(
                            asyncio.to_thread(
                                session.put,
                                "https://api.ngc.nvidia.com/self-onboard",
                                headers=so_headers,
                                json={"redirect_uri": "https://build.nvidia.com/", "email": email},
                                allow_redirects=False,
                                timeout=20,
                            ),
                            timeout=25.0,
                        )
                        log(f"[混合-3-HTTP] self-onboard PUT → HTTP {so_resp.status_code}: {so_resp.text[:200]}")
                    except asyncio.TimeoutError:
                        log("[混合-3-HTTP] self-onboard PUT 硬超时（SOCKS5 挂起），跳过")
                    except Exception as so_e:
                        log(f"[混合-3-HTTP] self-onboard PUT 异常: {so_e}")
                    # 2. POST /v3/orgs（直接创建 org）
                    log("[混合-3-HTTP] 尝试 POST /v3/orgs ...")
                    try:
                        org_resp = await asyncio.wait_for(
                            asyncio.to_thread(
                                session.post,
                                "https://api.ngc.nvidia.com/v3/orgs",
                                headers=so_headers,
                                json={"name": email.split("@")[0], "type": "PERSONAL", "displayName": email.split("@")[0]},
                                allow_redirects=False,
                                timeout=20,
                            ),
                            timeout=25.0,
                        )
                        log(f"[混合-3-HTTP] POST /v3/orgs → HTTP {org_resp.status_code}: {org_resp.text[:200]}")
                    except asyncio.TimeoutError:
                        log("[混合-3-HTTP] POST /v3/orgs 硬超时（SOCKS5 挂起），跳过")
                    except Exception as org_e:
                        log(f"[混合-3-HTTP] POST /v3/orgs 异常: {org_e}")
                log(f"[混合-3-HTTP] user-context 无 orgName，等待 3s 后重试 ({_uc_retry+1}/2) ...")
                await asyncio.sleep(3)
            log("[混合-3-HTTP] GET api.ngc.nvidia.com/user-context ...")
            # user-context 加 Bearer token（可能需要 token 才能返回完整 org 信息）
            uc_headers = {**ngc_headers}
            if current_key:
                uc_headers["authorization"] = f"Bearer {current_key}"
            try:
                resp = await asyncio.wait_for(
                    asyncio.to_thread(
                        session.get,
                        "https://api.ngc.nvidia.com/user-context",
                        headers=uc_headers,
                        timeout=20,
                    ),
                    timeout=25.0,
                )
            except asyncio.TimeoutError:
                log("[混合-3-HTTP] user-context GET 硬超时（SOCKS5 挂起），跳过到浏览器回退")
                break
            log(f"[混合-3-HTTP] user-context HTTP {resp.status_code}: {resp.text[:300]}")
            if resp.status_code != 200:
                # 401 时重新调 NGC login 刷新 session
                # 但 session 端点 Set-Cookie 已建立 session 时（_saved_cookies 为空），
                # NGC login 会覆盖 session cookie，不重试 login，仅等待后重试 user-context
                if resp.status_code == 401 and current_key and _saved_cookies:
                    log("[混合-3-HTTP] 401，重新调 NGC login 刷新 session...")
                    try:
                        lr = await asyncio.to_thread(session.get, ngc_login_url, headers=nav_headers, allow_redirects=False, timeout=30)
                        lc = lr.headers.get("location", "")
                        for _lh in range(6):
                            if not lc or urlparse(lc).hostname == "build.nvidia.com":
                                break
                            lr = await asyncio.to_thread(session.get, lc, headers=nav_headers, allow_redirects=False, timeout=30)
                            lc = lr.headers.get("location", "")
                    except Exception:
                        pass
                continue
            try:
                ctx_data = resp.json()
                org_name = ctx_data.get("orgName", "")
                if not org_name:
                    log(f"[混合-3-HTTP] user-context 响应 keys: {sorted(ctx_data.keys()) if isinstance(ctx_data, dict) else type(ctx_data).__name__}")
            except Exception:
                pass
            if org_name:
                break
        if not org_name:
            # 捕获完整 session cookies（含 domain），供浏览器外科手术式创建 org 使用
            full_cookies: list[dict[str, Any]] = []
            try:
                for c in session.cookies.jar:
                    full_cookies.append({
                        "name": c.name,
                        "value": c.value,
                        "domain": c.domain,
                        "path": c.path or "/",
                    })
            except Exception:
                pass
            return {
                "ok": False,
                "email_verified": True,
                "key": current_key,
                "cookies": response_cookies,
                "session_cookies": full_cookies,
                "ua": ua,
                "self_onboard_url": _self_onboard_url,
                "need_browser_org": True,
                "reason": "NGC user-context 无 orgName（重试 2 次）",
            }
        log(f"[混合-3-HTTP] ✅ orgName={org_name}")

        # ── 步骤 11: POST API Key ──
        log("[混合-3-HTTP] POST API Key ...")
        api_key_payload = {
            "expiryDate": "2126-04-08T07:00:00Z",
            "name": "dev",
            "type": "AI_PLAYGROUNDS_KEY",
            "policies": [
                {
                    "product": "nv-cloud-functions",
                    "scopes": ["invoke_function"],
                    "resources": [{"id": "*", "type": "account-functions"}],
                }
            ],
        }
        resp = await asyncio.to_thread(session.post, 
            f"https://api.ngc.nvidia.com/v3/orgs/{org_name}/keys/type/AI_PLAYGROUNDS_KEY",
            headers={**ngc_headers, "content-type": "application/json"},
            json=api_key_payload,
            timeout=30,
        )
        if resp.status_code not in (200, 201):
            return {
                "ok": False,
                "email_verified": True,
                "key": current_key,
                "cookies": response_cookies,
                "reason": f"NGC API Key HTTP {resp.status_code}: {resp.text[:200]}",
            }
        try:
            key_data = resp.json()
        except Exception:
            key_data = {}
        api_key = ""
        if isinstance(key_data, dict):
            api_key = (key_data.get("key") or {}).get("value", "") if isinstance(key_data.get("key"), dict) else ""
            if not api_key:
                api_key = (key_data.get("apiKey") or {}).get("value", "") if isinstance(key_data.get("apiKey"), dict) else ""
        if not api_key:
            return {
                "ok": False,
                "email_verified": True,
                "key": current_key,
                "cookies": response_cookies,
                "reason": f"NGC API Key 响应无 key.value: {str(key_data)[:200]}",
            }

        log(f"[混合-3-HTTP] ✅ 纯 HTTP 拿到 API Key: {api_key[:20]}...")
        # 更新 cookies
        try:
            for cookie in session.cookies.jar:
                response_cookies[cookie.name] = cookie.value
        except Exception:
            pass
        return {
            "ok": True,
            "email_verified": True,
            "apikey": api_key,
            "key": current_key,
            "cookies": response_cookies,
            "reason": "纯 HTTP 阶段 3 全流程成功",
        }
    except Exception as exc:
        return {"ok": False, "reason": f"阶段 3 HTTP 请求异常: {exc}", "key": current_key}


async def _browser_create_org(
    *,
    proxy_info: ProxyInfo,
    config: dict[str, Any] | None,
    project_id: str,
    session_cookies: list[dict[str, Any]],
    self_onboard_url: str,
    email: str,
    password: str,
    log,
) -> dict[str, Any]:
    """外科手术式浏览器 org 创建：仅用浏览器处理 select-account SPA 页面。

    HTTP 流程已完成登录/consent/session 建立，但 user-context 无 orgName（org 未创建）。
    select-account 是 Next.js SPA，HTTP 无法交互。

    策略：注入 HTTP session cookies（含 .accounts.nvgs.nvidia.com 上的 MainAuth_2/3/4）
    到浏览器，然后导航到 NGC login URL（api.ngc.nvidia.com/login）。NGC login 会重定向到
    NVGS OAuth（accounts.nvgs.nvidia.com），NVGS 识别已注入的 session cookies → 自动重定向
    到 callback → 建立 NGC session + 设置 web cookies → self-onboard → select-account。
    然后复用 _flow._handle_select_account 创建 org。

    返回 {"ok": bool, "cookies": list[dict]} — cookies 含浏览器端的最新 cookies。
    """
    from urllib.parse import urlencode as _urlencode

    browser_backend = resolve_browser_backend(config, project_id=project_id)
    browser_channel = "chrome"
    if config:
        project_cfg = (config.get("projects") or {}).get(project_id) or {}
        browser_channel = str(project_cfg.get("browser_channel") or "chrome").strip()
    log(f"[混合-3-浏览器] 底座={browser_backend}, channel={browser_channel}")

    # NGC login URL — 触发完整 OAuth 流程（NVGS OAuth 在 accounts.nvgs.nvidia.com，
    # 我们有 MainAuth_2/3/4 cookies，NVGS 会识别已登录并自动重定向到 callback）
    ngc_login_url = (
        f"https://api.ngc.nvidia.com/login?"
        + _urlencode({"email": email, "app": "api-catalog", "redirect_uri": "https://build.nvidia.com/"})
    )

    async with browser_session(
        proxy_info=proxy_info,
        browser_channel=browser_channel,
        browser_backend=browser_backend,
        user_agent="",
    ) as (context, page):
        try:
            # 1. 注入 HTTP session cookies 到浏览器
            if session_cookies:
                pw_cookies = []
                for c in session_cookies:
                    domain = c.get("domain", ".nvidia.com")
                    pw_cookies.append({
                        "name": c["name"],
                        "value": c["value"],
                        "domain": domain,
                        "path": c.get("path", "/"),
                    })
                try:
                    await context.add_cookies(pw_cookies)
                    log(f"[混合-3-浏览器] 已注入 {len(pw_cookies)} 个 cookies")
                except Exception as ce:
                    log(f"[混合-3-浏览器] 注入 cookies 异常（忽略）: {ce}")

            # 2. 导航到 NGC login URL — 触发 OAuth 重定向链
            log(f"[混合-3-浏览器] 导航到 NGC login: {ngc_login_url[:90]}...")
            try:
                await page.goto(ngc_login_url, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                log(f"[混合-3-浏览器] NGC login goto 异常（忽略）: {str(e)[:120]}")

            # 3. 等待 OAuth 重定向链完成
            log("[混合-3-浏览器] 等待 OAuth 重定向链完成...")
            reached_select_account = False
            _password_filled = False
            for _w in range(30):
                await page.wait_for_timeout(2000)
                cur_url = (page.url or "").lower()
                if "select-account" in cur_url or "cloudaccounts" in cur_url:
                    log(f"[混合-3-浏览器] ✅ 到达 select-account: {(page.url or '')[:80]}")
                    reached_select_account = True
                    break
                if "build.nvidia.com" in cur_url and "modal=signin" not in cur_url:
                    log(f"[混合-3-浏览器] ✅ 到达 build.nvidia.com（org 可能已存在）: {cur_url[:80]}")
                    break
                # NVGS 不认注入的 cookies → 重定向到密码页，需浏览器填密码登录
                if "/login/password" in cur_url and not _password_filled:
                    log(f"[混合-3-浏览器] 检测到 NVGS 密码页，填写密码登录...")
                    _password_filled = True
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=10000)
                    except Exception:
                        pass
                    # 填密码
                    pwd_filled = False
                    for sel in ('input[type="password"]', 'input[name="password"]', '#password'):
                        try:
                            pwd_el = page.locator(sel).first
                            if await pwd_el.count() > 0:
                                await pwd_el.fill(password)
                                pwd_filled = True
                                log(f"[混合-3-浏览器] 密码已填写 (sel={sel})")
                                break
                        except Exception:
                            continue
                    if not pwd_filled:
                        log(f"[混合-3-浏览器] ⚠️ 未找到密码输入框，页面 URL: {cur_url[:80]}")
                        continue
                    # 点提交
                    for sel in (
                        "button[type='submit']",
                        "button:has-text('Sign In')",
                        "button:has-text('Continue')",
                        "button.btn-primary",
                    ):
                        try:
                            btn = page.locator(sel).first
                            if await btn.count() > 0:
                                await btn.click()
                                log(f"[混合-3-浏览器] 已点击提交 (sel={sel})")
                                break
                        except Exception:
                            continue
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=15000)
                    except Exception:
                        pass
                    continue
                # login 页可能需要 JS 自动提交，等待
                if "login.nvgs.nvidia.com" in cur_url or "login.nvidia.com" in cur_url:
                    try:
                        await page.wait_for_load_state("networkidle", timeout=5000)
                    except Exception:
                        pass
                    continue
            else:
                log(f"[混合-3-浏览器] ⚠️ 重定向链未到达预期页面: {(page.url or '')[:80]}")

            # 4. 如果到达 select-account，处理 SPA（填 org name + Create）
            if reached_select_account or "select-account" in (page.url or "").lower():
                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                from . import _flow
                log("[混合-3-浏览器] 调用 _handle_select_account...")
                try:
                    await _flow._handle_select_account(page)
                except Exception as e:
                    log(f"[混合-3-浏览器] _handle_select_account 异常: {e}")

                # 5. 等待离开 select-account（org 创建后重定向）
                _org_redirect_ok = False
                for _w in range(20):
                    await page.wait_for_timeout(2000)
                    cur_url = page.url or ""
                    if "build.nvidia.com" in cur_url:
                        log(f"[混合-3-浏览器] ✅ org 创建后到达 build.nvidia.com: {cur_url[:80]}")
                        _org_redirect_ok = True
                        break
                    if "chrome-error" in cur_url:
                        log(f"[混合-3-浏览器] ⚠️ org 创建后网络错误（chrome-error），重新导航 NGC login 恢复 session...")
                        # org 可能已在服务端创建，但浏览器重定向失败。
                        # 重新导航 NGC login URL，利用 NVGS session（密码登录已建立）走 OAuth 链恢复 NGC session。
                        try:
                            await page.goto(ngc_login_url, wait_until="domcontentloaded", timeout=30000)
                        except Exception as e:
                            log(f"[混合-3-浏览器] 重新导航 NGC login 异常（忽略）: {str(e)[:120]}")
                        # 等待 OAuth 链到达 build.nvidia.com
                        for _w2 in range(15):
                            await page.wait_for_timeout(2000)
                            cur_url2 = page.url or ""
                            if "build.nvidia.com" in cur_url2:
                                log(f"[混合-3-浏览器] ✅ 恢复后到达 build.nvidia.com: {cur_url2[:80]}")
                                _org_redirect_ok = True
                                break
                            if "select-account" in cur_url2 or "cloudaccounts" in cur_url2:
                                log(f"[混合-3-浏览器] ⚠️ 恢复后又回到 select-account（org 未创建？）: {cur_url2[:80]}")
                                break
                        break
                    if "select-account" not in cur_url and "cloudaccounts" not in cur_url and "chrome-error" not in cur_url:
                        log(f"[混合-3-浏览器] ✅ 已离开 cloudaccounts: {cur_url[:80]}")
                        _org_redirect_ok = True
                        break
                else:
                    log(f"[混合-3-浏览器] ⚠️ 仍在 select-account: {(page.url or '')[:80]}")
                if not _org_redirect_ok:
                    log("[混合-3-浏览器] ⚠️ org 创建后重定向未成功，仍提取 cookies 供 HTTP 重试")
            else:
                log("[混合-3-浏览器] 未到达 select-account（org 可能已存在或需重试）")

            # 6. 提取浏览器端最新 cookies
            browser_cookies: list[dict[str, Any]] = []
            try:
                all_cookies = await context.cookies()
                for c in all_cookies:
                    browser_cookies.append({
                        "name": c.get("name", ""),
                        "value": c.get("value", ""),
                        "domain": c.get("domain", ".nvidia.com"),
                        "path": c.get("path", "/"),
                    })
                log(f"[混合-3-浏览器] 提取 {len(browser_cookies)} 个 cookies")
            except Exception as ce:
                log(f"[混合-3-浏览器] 提取 cookies 异常: {ce}")

            return {"ok": True, "cookies": browser_cookies}
        except Exception as e:
            log(f"[混合-3-浏览器] 外科手术式 org 创建异常: {e}")
            return {"ok": False, "cookies": []}


async def _http_get_apikey_with_cookies(
    *,
    proxy_server: str,
    browser_cookies: list[dict[str, Any]],
    key: str,
    ua: str,
    email: str,
    log,
) -> dict[str, Any]:
    """浏览器创建 org 后，HTTP 重试 user-context + API key。

    用浏览器端 cookies 建立 curl_cffi session，GET user-context 获取 orgName，
    然后 POST API key。绕过 select-account SPA 的 JS 限制。
    """
    from curl_cffi import requests as cc_requests

    session = cc_requests.Session(impersonate="chrome145")
    if proxy_server:
        session.proxies = {"http": proxy_server, "https": proxy_server}

    # SOCKS5 代理偶发连接关闭，自动重试
    _orig_get = session.get
    _orig_post = session.post

    def _retrying_get(url, *args, **kwargs):
        last_err: Exception | None = None
        for _ in range(3):
            try:
                return _orig_get(url, *args, **kwargs)
            except Exception as e:
                last_err = e
                log(f"[混合-3-HTTP重试] GET 重试: {str(e)[:120]}")
        raise last_err  # type: ignore[misc]

    def _retrying_post(url, *args, **kwargs):
        last_err: Exception | None = None
        for _ in range(3):
            try:
                return _orig_post(url, *args, **kwargs)
            except Exception as e:
                last_err = e
                log(f"[混合-3-HTTP重试] POST 重试: {str(e)[:120]}")
        raise last_err  # type: ignore[misc]

    session.get = _retrying_get  # type: ignore[assignment]
    session.post = _retrying_post  # type: ignore[assignment]

    # 注入浏览器 cookies
    for c in browser_cookies:
        try:
            session.cookies.set(c["name"], c["value"], domain=c.get("domain", ".nvidia.com"))
        except Exception:
            pass
    log(f"[混合-3-HTTP重试] 已注入 {len(browser_cookies)} 个浏览器 cookies")

    ngc_headers = {
        "accept": "application/json, text/plain, */*",
        "user-agent": ua or "",
    }
    if key:
        ngc_headers["authorization"] = f"Bearer {key}"

    # 1. GET user-context → orgName
    org_name = ""
    for _uc in range(5):
        if _uc > 0:
            await asyncio.sleep(3)
            log(f"[混合-3-HTTP重试] user-context 重试 ({_uc+1}/5)...")
        try:
            resp = await asyncio.wait_for(
                asyncio.to_thread(
                    session.get,
                    "https://api.ngc.nvidia.com/user-context",
                    headers=ngc_headers,
                    timeout=20,
                ),
                timeout=25.0,
            )
            log(f"[混合-3-HTTP重试] user-context HTTP {resp.status_code}: {resp.text[:200]}")
            if resp.status_code == 200:
                ctx_data = resp.json() if resp.text else {}
                org_name = ctx_data.get("orgName", "") if isinstance(ctx_data, dict) else ""
                if org_name:
                    log(f"[混合-3-HTTP重试] ✅ orgName={org_name}")
                    break
        except asyncio.TimeoutError:
            log(f"[混合-3-HTTP重试] user-context 硬超时（SOCKS5 挂起），重试 ({_uc+1}/5)")
        except Exception as e:
            log(f"[混合-3-HTTP重试] user-context 异常: {e}")

    if not org_name:
        return {"ok": False, "reason": "浏览器创建 org 后 user-context 仍无 orgName"}

    # 2. POST API Key
    api_key_payload = {
        "expiryDate": "2126-04-08T07:00:00Z",
        "name": "dev",
        "type": "AI_PLAYGROUNDS_KEY",
        "policies": [
            {
                "product": "nv-cloud-functions",
                "scopes": ["invoke_function"],
                "resources": [{"id": "*", "type": "account-functions"}],
            }
        ],
    }
    try:
        resp = await asyncio.wait_for(
            asyncio.to_thread(
                session.post,
                f"https://api.ngc.nvidia.com/v3/orgs/{org_name}/keys/type/AI_PLAYGROUNDS_KEY",
                headers={**ngc_headers, "content-type": "application/json"},
                json=api_key_payload,
                timeout=20,
            ),
            timeout=25.0,
        )
        if resp.status_code not in (200, 201):
            return {"ok": False, "reason": f"API Key HTTP {resp.status_code}: {resp.text[:200]}"}
        key_data = resp.json() if resp.text else {}
    except asyncio.TimeoutError:
        return {"ok": False, "reason": "API Key POST 硬超时（SOCKS5 挂起）"}
    except Exception as e:
        return {"ok": False, "reason": f"API Key 请求异常: {e}"}

    api_key = ""
    if isinstance(key_data, dict):
        api_key = (key_data.get("key") or {}).get("value", "") if isinstance(key_data.get("key"), dict) else ""
        if not api_key:
            api_key = (key_data.get("apiKey") or {}).get("value", "") if isinstance(key_data.get("apiKey"), dict) else ""
    if not api_key:
        return {"ok": False, "reason": f"API Key 响应无 key.value: {str(key_data)[:200]}"}

    log(f"[混合-3-HTTP重试] ✅ 拿到 API Key: {api_key[:20]}...")
    return {"ok": True, "apikey": api_key, "org_name": org_name}


async def _browser_otp_and_apikey(
    *,
    page,
    context,
    email: str,
    password: str,
    new_key: str,
    resp_cookies: dict[str, str],
    client_id: str,
    wait_code_fn,
    wait_link_fn=None,
    log,
) -> str | None:
    """阶段 3: 浏览器登录已注册账号 → profile-complete → OTP → consent → API Key

    curl_cffi 注册后浏览器 session 不匹配 profile-complete 的 key。
    改为：浏览器通过 build.nvidia.com signin 登录已注册账号，
    让 NVGS 自然建立 session → 跳 profile-complete（OTP）→ consent → API Key。

    支持两种邮箱验证模式：
      - OTP 输入（默认）：6 位验证码填入输入框
      - 点击邮件链接：从邮件提取验证 URL 并导航（需 wait_link_fn）

    Returns: apikey 或 None
    """
    from . import _flow

    # #region debug-point A-E:stage3-network
    async def on_request(request):
        host = urlparse(request.url).hostname or ""
        if host not in _DEBUG_DOMAINS:
            return
        _debug_report("A", "_browser_otp_and_apikey:request", "stage3 request", {
            "method": request.method,
            "url": _debug_redacted_url(request.url),
            "body": _debug_body_shape(request.post_data),
            "header_names": sorted(name.lower() for name in request.headers if name.lower() not in {"cookie", "authorization"}),
        })

    async def on_response(response):
        host = urlparse(response.url).hostname or ""
        if host not in _DEBUG_DOMAINS:
            return
        headers = await response.all_headers()
        location = headers.get("location", "")
        set_cookie = headers.get("set-cookie", "")
        response_shape = None
        content_type = headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                response_shape = _debug_value_shape(await response.json())
            except Exception:
                response_shape = {"unreadable": True}
        _debug_report("E", "_browser_otp_and_apikey:response", "stage3 response", {
            "status": response.status,
            "url": _debug_redacted_url(response.url),
            "location": _debug_redacted_url(location) if location else "",
            "set_cookie_names": sorted({part.split("=", 1)[0].strip() for part in set_cookie.split(",") if "=" in part}),
            "json_shape": response_shape,
        })

        # ★ 关键端点（self-onboard/session/user-context/orgs/select-account/nca_picker）
        # 保存完整响应到文件，用于分析 org 创建的真实 API（curl_cffi 无法执行 JS）
        _url_lower = response.url.lower()
        if any(k in _url_lower for k in ("self-onboard", "/session", "user-context", "/orgs", "select-account", "cloudaccounts", "nca_picker", "callback/consent", "callback/redirect")):
            try:
                import json as _json_mod, time as _time_mod, os as _os_mod
                _capture_dir = "data/debug/nvidia_build"
                _os_mod.makedirs(_capture_dir, exist_ok=True)
                _body_text = ""
                try:
                    _body_text = await response.text()
                except Exception:
                    pass
                _entry = {
                    "ts": _time_mod.time(),
                    "method": response.request.method,
                    "url": response.url,
                    "status": response.status,
                    "location": location,
                    "set_cookie": set_cookie[:500] if set_cookie else "",
                    "content_type": content_type,
                    "body": _body_text[:3000],
                }
                with open(_os_mod.path.join(_capture_dir, "stage3_capture.jsonl"), "a", encoding="utf-8") as _cf:
                    _cf.write(_json_mod.dumps(_entry, ensure_ascii=False) + "\n")
            except Exception:
                pass

    page.on("request", on_request)
    page.on("response", on_response)
    # #endregion

    def sync_fetch_code(target_email: str, timeout: int = 120):
        """把 async wait_code_fn 包装成同步函数（_flow.step12 用 run_in_executor 调）"""
        try:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(wait_code_fn(target_email, timeout=timeout))
            finally:
                loop.close()
        except Exception as exc:
            log(f"[混合-3] 读验证码异常: {exc}")
            return None

    _flow.set_code_fetcher(sync_fetch_code)
    _flow.PASSWORD = password

    # 1. 通过 build.nvidia.com signin 登录已注册账号（代理偶发 chrome-error，最多重试 3 次）
    pwd_appeared = False
    for login_attempt in range(3):
        if login_attempt > 0:
            log(f"[混合-3] === 登录重试第 {login_attempt+1} 次（之前 chrome-error/未加载）===")
            await page.wait_for_timeout(3000)

        log("[混合-3] 浏览器登录已注册账号（build.nvidia.com signin）...")
        ok = await _flow.step1_open_signin(page)
        if not ok:
            log("[混合-3] ❌ 打开 signin 失败")
            if login_attempt < 2:
                continue
            return None
        try:
            await _flow.step2_accept_cookies(page)
        except Exception:
            pass

        # cookie 点击后页面可能正在重载，等加载稳定再填邮箱
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            pass
        await page.wait_for_timeout(1000)

        # 填邮箱 + 点 Next（账号已注册，NVGS 会显示密码登录而非注册表单）
        # page.evaluate 偶发 "Execution context was destroyed"（页面正在导航），
        # 用 Playwright locator + try/except 更稳，失败则跳过让下方等待循环接管。
        log(f"[混合-3] 填邮箱 + 点 Next ...")
        try:
            email_loc = page.locator("input[name='email'], input[type='email']").first
            try:
                await email_loc.click(timeout=5000)
            except Exception:
                pass
            await email_loc.fill(email)
            await page.wait_for_timeout(800)
            # 优先用 Playwright locator 点 Next（避免 evaluate 在导航中失败）
            next_clicked = False
            for sel in [
                ".nv-modal-content button.btn-primary.btn-lg.btn-rounded:visible",
                "button:has-text('Next'):visible",
                "button.btn-primary:visible",
            ]:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible():
                        await loc.click(no_wait_after=True, timeout=5000)
                        next_clicked = True
                        log(f"[混合-3] 已点击 Next: {sel}")
                        break
                except Exception:
                    continue
            if not next_clicked:
                # 兜底：evaluate（可能因导航中失败，但已尽力）
                try:
                    await page.evaluate("""() => {
                        const btns = Array.from(document.querySelectorAll('button'))
                            .filter(b => b.offsetParent !== null);
                        let b = btns.find(b => b.textContent.trim() === 'Next');
                        if (!b) b = btns.find(b => /next|continue/i.test(b.textContent) && /btn-primary|primary/.test(b.className));
                        if (b) b.click();
                    }""")
                except Exception as e:
                    log(f"[混合-3] ⚠️ 点击 Next evaluate 异常（可能已导航）: {str(e)[:100]}")
        except Exception as e:
            log(f"[混合-3] ⚠️ 填邮箱/点 Next 异常: {str(e)[:100]}")

        # 2. 等 NVGS 页面加载（标识页或密码页）— 最多 15s
        #    若超时（Angular 加载慢），第二个循环会接管密码页处理
        log("[混合-3] 等 NVGS 页面加载 ...")
        chrome_error = False
        for i in range(15):
            await page.wait_for_timeout(1000)
            url = page.url or ""
            # chrome-error: 代理 tunnel 失败或连接被重置
            if url.startswith("chrome-error://"):
                log(f"[混合-3] ⚠️ 页面落到 chrome-error ({i+1}s)，代理 tunnel 异常")
                chrome_error = True
                break
            if "nvgs" in url or ("login" in url and "build.nvidia" not in url):
                # 检查是否有 #loginNextButton（标识页）
                next_btn = await page.locator("#loginNextButton").count()
                if next_btn > 0:
                    log(f"[混合-3] NVGS 标识页，点击 #loginNextButton ({i+1}s)")
                    try:
                        await page.locator("#loginNextButton").click(force=True, no_wait_after=True, timeout=10000)
                    except Exception as e:
                        log(f"[混合-3] 点击 #loginNextButton 异常: {e}")
                    await page.wait_for_timeout(2000)
                    continue
                # 检查是否有密码输入框
                pwd_cnt = await page.locator("input[type='password']:visible").count()
                if pwd_cnt > 0:
                    log(f"[混合-3] 密码输入框已出现 ({i+1}s)")
                    pwd_appeared = True
                    break
                # 检查是否已有 OTP（profile-complete）
                otp_cnt = await page.locator("input[maxlength='1']:visible").count()
                if otp_cnt > 0:
                    log(f"[混合-3] 直接到 OTP 页 ({i+1}s)")
                    pwd_appeared = True  # 跳过密码填写
                    break
                # 检查是否已到 build.nvidia.com
                if "build.nvidia" in url:
                    log(f"[混合-3] 已到 build.nvidia.com ({i+1}s)")
                    break
        if chrome_error:
            # 代理 tunnel 异常，重试整个登录流程
            if login_attempt < 2:
                log("[混合-3] chrome-error，重试登录 ...")
                continue
            log("[混合-3] ❌ 3 次重试后仍 chrome-error")
            return None
        # 成功加载（pwd_appeared 或 已到 build.nvidia.com 或 已到 OTP）
        break

    # 3. 填密码 + 点 Sign In
    if pwd_appeared:
        pwd_loc = page.locator("input[type='password']:visible").first
        if await pwd_loc.count() > 0:
            log(f"[混合-3] 填密码 ...")
            await pwd_loc.fill(password)
            await page.wait_for_timeout(500)
            # 点登录按钮
            clicked = await page.evaluate("""() => {
                const btns = Array.from(document.querySelectorAll('button'))
                    .filter(b => b.offsetParent !== null);
                let b = btns.find(b => /sign in|log in|continue|登录|继续/i.test(b.textContent));
                if (b) { b.click(); return true; }
                // 兜底：btn-primary
                b = btns.find(b => /btn-primary/.test(b.className));
                if (b) { b.click(); return true; }
                return false;
            }""")
            log(f"[混合-3] 点击登录按钮: {clicked}")
            await page.wait_for_timeout(3000)

    log(f"[混合-3] 登录后 URL: {page.url[:80]}")

    # 4. 等跳到 profile-complete / consent / build.nvidia
    #    同时处理 NVGS 登录中间页（identifier → password），因为第一个等待循环
    #    可能因 Angular 加载慢而超时退出，密码页在第二个循环才出现。
    otp_ready = False
    link_verify = False  # "点击邮件链接" 验证模式
    pwd_filled = False   # 密码是否已填写（避免重复填写）
    last_logged_url = ""
    for i in range(60):
        await page.wait_for_timeout(1000)
        url = page.url or ""
        # URL 变化时记录（调试 save-login 等中间页跳转）
        if url != last_logged_url:
            log(f"[混合-3] URL({i+1}s): {url[:100]}")
            last_logged_url = url
        # chrome-error: 代理 tunnel 异常
        if url.startswith("chrome-error://"):
            log(f"[混合-3] ⚠️ chrome-error ({i+1}s)")
            break

        # —— NVGS 登录中间页处理（identifier / password）——
        # 标识页：点 #loginNextButton 推进到密码页
        if not pwd_filled and ("nvgs" in url or "/login/" in url):
            next_btn = await page.locator("#loginNextButton").count()
            if next_btn > 0:
                log(f"[混合-3] NVGS 标识页，点 #loginNextButton ({i+1}s)")
                try:
                    await page.locator("#loginNextButton").click(force=True, no_wait_after=True, timeout=10000)
                except Exception as e:
                    log(f"[混合-3] 点 #loginNextButton 异常: {e}")
                await page.wait_for_timeout(2000)
                continue
            # 密码页：填密码 + 点 Sign In
            pwd_cnt = await page.locator("input[type='password']:visible").count()
            if pwd_cnt > 0:
                log(f"[混合-3] 密码输入框出现 ({i+1}s)，填密码 ...")
                try:
                    pwd_loc = page.locator("input[type='password']:visible").first
                    await pwd_loc.fill(password)
                    await page.wait_for_timeout(500)
                    # 点登录按钮（Sign In / Continue / 提交）
                    clicked = await page.evaluate("""() => {
                        const btns = Array.from(document.querySelectorAll('button'))
                            .filter(b => b.offsetParent !== null);
                        let b = btns.find(b => /sign in|log in|continue|登录|继续/i.test(b.textContent));
                        if (b) { b.click(); return true; }
                        b = btns.find(b => /btn-primary/.test(b.className));
                        if (b) { b.click(); return true; }
                        return false;
                    }""")
                    log(f"[混合-3] 点登录按钮: {clicked}")
                    pwd_filled = True
                    await page.wait_for_timeout(3000)
                except Exception as e:
                    log(f"[混合-3] ⚠️ 填密码异常: {e}")
                    pwd_filled = True  # 标记已尝试，避免无限重试
                continue

        # —— 跳转目标检测 ——
        if "profile-complete" in url:
            pass  # 继续等 OTP 或 click-link
        elif "consent" in url:
            log(f"[混合-3] 已到 consent ({i+1}s)")
            break
        elif "save-login" in url:
            # NVGS "保存登录信息?" 页：点 Not now / Skip 跳过，等自动跳到 profile-complete/consent
            if i % 5 == 0:  # 每 5s 尝试一次，避免频繁点击
                log(f"[混合-3] save-login 页，尝试跳过 ({i+1}s) ...")
                try:
                    clicked = await page.evaluate("""() => {
                        const btns = Array.from(document.querySelectorAll('button, a'))
                            .filter(b => b.offsetParent !== null);
                        // 优先 "Not now" / "Skip" / "暂不" / "跳过"
                        let b = btns.find(b => /not now|skip|later|暂不|跳过|以后/i.test(b.textContent||''));
                        if (b) { b.click(); return 'skip'; }
                        // 兜底：btn-secondary / btn-outline（非主按钮）
                        b = btns.find(b => /btn-secondary|btn-outline|secondary/.test(b.className));
                        if (b) { b.click(); return 'secondary'; }
                        return false;
                    }""")
                    if clicked:
                        log(f"[混合-3] save-login 点击了: {clicked}")
                        await page.wait_for_timeout(2000)
                except Exception:
                    pass
        elif "build.nvidia" in url and "modal=signin" not in url:
            # build.nvidia.com（非 signin 模态框）：可能已验证或跳过验证
            if i > 3:
                log(f"[混合-3] 已到 build.nvidia.com ({i+1}s)，跳过 OTP")
                break
        otp_cnt = await page.locator("input[maxlength='1']:visible").count()
        if otp_cnt > 0:
            log(f"[混合-3] OTP 输入框已出现 ({i+1}s, {otp_cnt} 格)")
            otp_ready = True
            break
        # 检测"点击邮件链接"验证模式（保守：等 10s 确认无 OTP 输入框）
        if "profile-complete" in url and i >= 10 and wait_link_fn is not None:
            body_text = await page.evaluate("() => document.body.innerText.substring(0, 800)")
            # 英文关键词（NVIDIA 页面通常英文）
            has_click = any(kw in body_text.lower() for kw in ("click", "clicking", "tap"))
            has_link = "link" in body_text.lower()
            has_email = "email" in body_text.lower()
            # 中文关键词（兜底）
            has_cn = ("点击" in body_text and "链接" in body_text and "邮件" in body_text)
            if (has_click and has_link and has_email) or has_cn:
                log(f"[混合-3] 检测到'点击邮件链接'验证模式 ({i+1}s)")
                link_verify = True
                break

    # 5. 处理验证
    if link_verify:
        # "点击邮件链接"模式：从邮件中提取验证链接并导航
        log("[混合-3] 从邮件提取验证链接 ...")
        verify_link = await _extract_verify_link(wait_link_fn, email, log, timeout=120)
        if verify_link:
            log(f"[混合-3] 导航到验证链接: {verify_link[:80]} ...")
            try:
                await page.goto(verify_link, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                log(f"[混合-3] ⚠️ 导航验证链接异常: {e}")
            await page.wait_for_timeout(3000)
            log(f"[混合-3] 验证后 URL: {page.url[:80]}")

            # verify-email 页通常不会自动跳回 consent/build；
            # 等待可能的 Continue 按钮 / 自动重定向（最多 15s）
            redirected = False
            for i in range(15):
                cur = page.url or ""
                if "consent" in cur or "build.nvidia" in cur or "/v1/login" in cur:
                    log(f"[混合-3] 验证后已跳转 ({i+1}s): {cur[:80]}")
                    redirected = True
                    break
                # 找 Continue / Done / 返回 按钮
                try:
                    clicked = await page.evaluate("""() => {
                        const b = Array.from(document.querySelectorAll('button, a'))
                            .find(n => n.offsetParent !== null && /continue|done|return|back|返回|继续|完成/i.test(n.textContent||''));
                        if (b) { b.click(); return true; }
                        return false;
                    }""")
                    if clicked:
                        log(f"[混合-3] 点击了验证页 Continue/返回按钮 ({i+1}s)")
                        await page.wait_for_timeout(3000)
                        continue
                except Exception:
                    pass
                await page.wait_for_timeout(1000)

            # 如果还停在 verify-email 页，重新走 signin 流程让 NVGS 建立 session
            cur = page.url or ""
            if not redirected and ("verify-email" in cur or "profile-management" in cur):
                log("[混合-3] 验证页未跳转，重新走 signin 让 NVGS 建立 session ...")
                try:
                    await page.goto("https://build.nvidia.com/?modal=signin", wait_until="domcontentloaded", timeout=30000)
                except Exception as e:
                    log(f"[混合-3] ⚠️ 重新打开 signin 异常: {e}")
                await page.wait_for_timeout(3000)
                # 填邮箱 + 点 Next（账号已验证，应跳过 OTP 直接到 consent/build）
                try:
                    email_loc2 = page.locator("input[name='email'], input[type='email']").first
                    if await email_loc2.count() > 0:
                        await email_loc2.fill(email)
                        await page.wait_for_timeout(800)
                        # 点 Next
                        for sel in [
                            ".nv-modal-content button.btn-primary.btn-lg.btn-rounded:visible",
                            "button:has-text('Next'):visible",
                            "button.btn-primary:visible",
                        ]:
                            try:
                                loc = page.locator(sel).first
                                if await loc.count() > 0 and await loc.is_visible():
                                    await loc.click(no_wait_after=True, timeout=5000)
                                    break
                            except Exception:
                                continue
                except Exception as e:
                    log(f"[混合-3] ⚠️ 重新填邮箱异常: {e}")
                # 等跳到 NVGS / consent / build（最多 30s）
                # 注意：modal=signin 不算"已到目标"，必须离开 signin 模态框才算
                relogin_pwd_filled = False
                for i in range(30):
                    await page.wait_for_timeout(1000)
                    cur = page.url or ""
                    if cur.startswith("chrome-error://"):
                        log(f"[混合-3] ⚠️ 重新登录落到 chrome-error ({i+1}s)")
                        break
                    # consent 或 build.nvidia.com（非 signin 模态框）= 已到目标
                    if "consent" in cur or ("build.nvidia" in cur and "modal=signin" not in cur):
                        log(f"[混合-3] 重新登录已到目标 ({i+1}s): {cur[:80]}")
                        break
                    if "nvgs" in cur or "login" in cur:
                        # 标识页 → 点 #loginNextButton
                        next_btn = await page.locator("#loginNextButton").count()
                        if next_btn > 0:
                            try:
                                await page.locator("#loginNextButton").click(force=True, no_wait_after=True, timeout=10000)
                            except Exception:
                                pass
                            await page.wait_for_timeout(2000)
                            continue
                        # 密码页 → 填密码 + 提交（避免重复填写）
                        if not relogin_pwd_filled:
                            pwd_cnt = await page.locator("input[type='password']:visible").count()
                            if pwd_cnt > 0:
                                pwd_loc = page.locator("input[type='password']:visible").first
                                try:
                                    await pwd_loc.fill(password)
                                    await page.wait_for_timeout(500)
                                    await page.evaluate("""() => {
                                        const b = Array.from(document.querySelectorAll('button'))
                                            .find(n => n.offsetParent !== null && /sign in|log in|continue|登录|继续/i.test(n.textContent||''));
                                        if (b) b.click();
                                    }""")
                                    relogin_pwd_filled = True
                                except Exception:
                                    pass
                                await page.wait_for_timeout(3000)
                                continue
                log(f"[混合-3] 重新登录后 URL: {page.url[:80]}")
                # 兜底：如果未到 consent/build.nvidia.com，直接访问 build.nvidia.com 让 NVGS session 生效
                # 覆盖：signin 模态框、verify-email 页、login.nvgs.nvidia.com 根页、chrome-error
                cur = page.url or ""
                need_fallback = (
                    "modal=signin" in cur
                    or "verify-email" in cur
                    or cur.startswith("chrome-error://")
                    or ("nvgs.nvidia.com" in cur and "consent" not in cur)
                )
                if need_fallback:
                    log(f"[混合-3] 未到 consent/build，当前={cur[:60]}，直接访问 build.nvidia.com ...")
                    # chrome-error 时先等代理恢复
                    if cur.startswith("chrome-error://"):
                        await page.wait_for_timeout(5000)
                    for fb_attempt in range(3):
                        try:
                            await page.goto("https://build.nvidia.com/", wait_until="domcontentloaded", timeout=30000)
                            await page.wait_for_timeout(4000)
                            fb_url = page.url or ""
                            log(f"[混合-3] 直接访问后 URL (第{fb_attempt+1}次): {fb_url[:80]}")
                            # 如果跳到了 NVGS 登录页，说明 session 未建立，需重新登录
                            if "nvgs" in fb_url or "login" in fb_url:
                                if fb_attempt < 2:
                                    log("[混合-3] build.nvidia.com 跳到登录页，等 3s 重试 ...")
                                    await page.wait_for_timeout(3000)
                                    continue
                            break
                        except Exception as e:
                            log(f"[混合-3] ⚠️ 直接访问 build.nvidia.com 异常 (第{fb_attempt+1}次): {e}")
                            if fb_attempt < 2:
                                await page.wait_for_timeout(5000)
        else:
            log("[混合-3] ⚠️ 未提取到验证链接，回退到 OTP 模式 ...")
            # 回退：检查是否出现了 OTP 输入框
            otp_cnt = await page.locator("input[maxlength='1']:visible").count()
            if otp_cnt > 0 or "profile-complete" in page.url:
                log("[混合-3] 回退：调用 step12_verify_email ...")
                try:
                    ok = await _flow.step12_verify_email(page, email)
                except Exception as e:
                    log(f"[混合-3] step12 异常: {e}")
                    ok = False
                if not ok:
                    log("[混合-3] ❌ 回退 OTP 验证也未完成")
                    return None
                log(f"[混合-3] ✅ 回退 OTP 验证完成，URL: {page.url[:80]}")
            else:
                log("[混合-3] ❌ 既无验证链接也无 OTP 输入框")
                return None
    elif otp_ready or "profile-complete" in page.url:
        log("[混合-3] 调用 step12_verify_email ...")
        try:
            ok = await _flow.step12_verify_email(page, email)
        except Exception as e:
            log(f"[混合-3] step12 异常: {e}")
            ok = False
        if not ok:
            log("[混合-3] ❌ step12 邮箱验证未完成")
            return None
        log(f"[混合-3] ✅ OTP 验证完成，URL: {page.url[:80]}")

    # 6. 调用 step13_fetch_apikey 拿 API Key
    log("[混合-3] 调用 step13_fetch_apikey ...")
    try:
        apikey = await _flow.step13_fetch_apikey(page, email)
    except Exception as e:
        log(f"[混合-3] step13 异常: {e}")
        apikey = None

    if apikey:
        log(f"[混合-3] ✅ 拿到 API Key: {apikey[:20]}...")
    else:
        log("[混合-3] ❌ 未拿到 API Key")
    return apikey


async def _http_stage1_get_key(
    *,
    email: str,
    proxy_server: str,
    log,
) -> dict[str, Any] | None:
    """阶段 1 纯 HTTP：直调 api.ngc.nvidia.com/login 获取 NVGS key（无需浏览器/FlareSolverr）。

    api.ngc.nvidia.com/login 无 Bot Manager 保护，curl_cffi 直调 3 跳即可拿 key。
    链路：api.ngc.nvidia.com/login → login.nvidia.com/authorize →
          accounts.nvgs.nvidia.com/api/1/oauth/authorize →
          login.nvgs.nvidia.com/v1/login?...&key=xxx

    Returns:
        {key, client_id, cookies, ua, nvgs_url} 或 None
    """
    from curl_cffi import requests as cc_requests
    from urllib.parse import urlencode as _urlencode

    ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
    )

    session = cc_requests.Session(impersonate="chrome145")
    if proxy_server:
        session.proxies = {"http": proxy_server, "https": proxy_server}

    login_url = (
        "https://api.ngc.nvidia.com/login?"
        + _urlencode({
            "email": email,
            "app": "api-catalog",
            "redirect_uri": "https://build.nvidia.com/",
        })
    )

    nav_headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "user-agent": ua,
        "referer": "https://build.nvidia.com/",
    }

    log("[混合-1-HTTP] GET api.ngc.nvidia.com/login（纯 HTTP 获取 key）...")

    # SOCKS5 代理偶发 TLS connect error（BoringSSL 状态混乱，瞬时），
    # 每个 GET 重试 3 次即可恢复（实测：try1 失败 try2 成功）。
    async def _get_with_retry(url: str, label: str, retries: int = 3):
        last_err: Exception | None = None
        for attempt in range(retries):
            try:
                return await asyncio.to_thread(session.get, url, headers=nav_headers, allow_redirects=False, timeout=30)
            except Exception as e:
                last_err = e
                log(f"[混合-1-HTTP] {label} try{attempt+1}/{retries} 异常: {str(e)[:150]}")
                if attempt < retries - 1:
                    await asyncio.sleep(2)
        log(f"[混合-1-HTTP] {label} 3 次重试均失败: {last_err}")
        return None

    resp = await _get_with_retry(login_url, "初始GET")
    if resp is None:
        return None

    # 手动跟随重定向链，提取 key
    current_url = resp.headers.get("location", "")
    hop = 0
    key = None
    nvgs_url = None

    while current_url and hop < 10:
        hop += 1
        if not current_url.startswith("http"):
            current_url = f"https://api.ngc.nvidia.com{current_url}"

        parsed = urlparse(current_url)
        params = parse_qs(parsed.query)
        if "key" in params:
            key = params["key"][0]
            nvgs_url = current_url
            break

        resp = await _get_with_retry(current_url, f"hop{hop}")
        if resp is None:
            break
        current_url = resp.headers.get("location", "")

    if not key:
        log("[混合-1-HTTP] ❌ 未拿到 key")
        return None

    # 提取 session cookies
    cookies: dict[str, str] = {}
    try:
        for c in session.cookies.jar:
            cookies[c.name] = c.value
    except Exception:
        cookies = dict(session.cookies) if session.cookies else {}

    client_id = "1214762014100529152"

    log(f"[混合-1-HTTP] ✅ 纯 HTTP 拿到 key: {key[:24]}..., cookies: {len(cookies)}")

    return {
        "key": key,
        "client_id": client_id,
        "cookies": cookies,
        "ua": ua,
        "nvgs_url": nvgs_url or "",
    }


async def register_hybrid(
    *,
    email: str,
    password: str,
    proxy_info: ProxyInfo | None = None,
    config: dict[str, Any] | None = None,
    project_id: str = "nvidia_build",
    headless: bool = False,
    solve_captcha_fn=None,
    wait_code_fn=None,
    wait_link_fn=None,
    log=print,
) -> dict[str, Any] | None:
    """NVIDIA 混合模式注册入口

    Args:
        email: 注册邮箱
        password: 注册密码
        proxy_info: ProxyInfo（由 Provider 注入，自动处理认证转发器）
        config: 全局配置（用于解析 browser_backend）
        project_id: 项目 ID（用于解析项目级 browser_backend）
        headless: 是否无头
        solve_captcha_fn: async fn(sitekey, page_url, **kwargs) -> token
        wait_code_fn: async fn(email, timeout) -> code  （OTP 验证码）
        wait_link_fn: async fn(email, timeout) -> link   （验证链接，可选）
        log: 日志函数

    Returns:
        {"apikey": str, "email": str, "key": str} 或 None
    """
    if solve_captcha_fn is None:
        log("[混合] ❌ 未提供 solve_captcha_fn")
        return None
    if wait_code_fn is None:
        log("[混合] ❌ 未提供 wait_code_fn")
        return None

    log(f"[混合] 开始 NVIDIA HTTP 模式注册: {email}")

    # curl_cffi 用的代理地址（浏览器走 browser_session 内部处理）
    # 纯 HTTP 阶段无浏览器，本地 HTTP forwarder（proxy_info.server）可能未启动/已停止；
    # 优先用 upstream SOCKS5 直连（curl_cffi 原生支持带认证的 socks5://）。
    proxy_server = ""
    if proxy_info:
        upstream = (proxy_info.meta or {}).get("upstream")
        proxy_server = upstream or proxy_info.server
        log(f"[混合] HTTP 代理: {proxy_server} (server={proxy_info.server}, upstream={upstream})")

    # ── 阶段 1: 纯 HTTP 获取 key（不走浏览器，api.ngc.nvidia.com 无 Bot Manager）──
    cf_data = await _http_stage1_get_key(
        email=email,
        proxy_server=proxy_server,
        log=log,
    )

    new_key = ""
    resp_cookies: dict[str, str] = {}

    if cf_data:
        # ── 阶段 2: curl_cffi 提交注册 ──
        reg_result = await _http_register(
            email=email,
            password=password,
            cf_data=cf_data,
            proxy_server=proxy_server,
            solve_captcha_fn=solve_captcha_fn,
            log=log,
        )
        if not reg_result:
            log("[混合] ❌ 阶段 2 失败")
            return None

        new_key = reg_result.get("key") or ""
        resp_cookies = reg_result.get("cookies") or {}

        # ── 阶段 3a: 纯 HTTP 登录 + 邮件验证 + consent + API Key ──
        http_stage3 = await _http_stage3_verify_email(
            email=email,
            password=password,
            cf_data=cf_data,
            reg_result=reg_result,
            proxy_server=proxy_server,
            wait_link_fn=wait_link_fn,
            log=log,
        )
        if http_stage3.get("key"):
            new_key = http_stage3["key"]
        if http_stage3.get("cookies"):
            resp_cookies = http_stage3["cookies"]

        if http_stage3.get("ok") and http_stage3.get("apikey"):
            # 纯 HTTP 全流程成功，无需打开浏览器
            apikey = http_stage3["apikey"]
            log(f"[混合-3-HTTP] ✅ {http_stage3['reason']}，纯 HTTP 全流程成功")
            return {
                "apikey": apikey,
                "email": email,
                "key": new_key,
                "status": "ok",
            }

        # ── 外科手术式浏览器 org 创建（HTTP 已完成登录/consent/session，仅缺 org）──
        # select-account 是 Next.js SPA，HTTP 无法交互。注入 cookies 到浏览器，
        # 仅用浏览器处理 select-account 页面创建 org，然后 HTTP 拿 API key。
        if http_stage3.get("need_browser_org") and http_stage3.get("email_verified"):
            log("[混合-3-HTTP] ⚠️ HTTP org 创建失败（SPA 限制），浏览器外科手术式创建 org...")
            org_result = await _browser_create_org(
                proxy_info=proxy_info,
                config=config,
                project_id=project_id,
                session_cookies=http_stage3.get("session_cookies") or [],
                self_onboard_url=http_stage3.get("self_onboard_url") or "",
                email=email,
                password=password,
                log=log,
            )
            if org_result.get("ok"):
                log("[混合-3-HTTP] 浏览器 org 创建完成，HTTP 重试 user-context + API key...")
                retry_result = await _http_get_apikey_with_cookies(
                    proxy_server=proxy_server,
                    browser_cookies=org_result.get("cookies") or [],
                    key=new_key,
                    ua=http_stage3.get("ua") or (cf_data or {}).get("ua", ""),
                    email=email,
                    log=log,
                )
                if retry_result.get("ok") and retry_result.get("apikey"):
                    apikey = retry_result["apikey"]
                    log(f"[混合-3-HTTP] ✅ 浏览器创建 org + HTTP API key 全流程成功")
                    return {
                        "apikey": apikey,
                        "email": email,
                        "key": new_key,
                        "status": "ok",
                    }
                log(f"[混合-3-HTTP] ⚠️ HTTP 重试 API key 失败: {retry_result.get('reason', '')}")
            else:
                log("[混合-3-HTTP] ⚠️ 浏览器 org 创建失败，回退完整浏览器流程")

        log(f"[混合-3-HTTP] ⚠️ {http_stage3.get('reason', 'HTTP 阶段3未完成')}，打开浏览器回退")
    else:
        log("[混合-1-HTTP] ⚠️ 纯 HTTP 阶段 1 失败，回退浏览器完整流程")

    # ── 浏览器回退（阶段 1 失败或阶段 3 需要浏览器）──
    browser_backend = resolve_browser_backend(config, project_id=project_id)
    browser_channel = "chrome"
    if config:
        project_cfg = (config.get("projects") or {}).get(project_id) or {}
        browser_channel = str(project_cfg.get("browser_channel") or "chrome").strip()
    log(f"[混合] 浏览器底座: {browser_backend}, channel: {browser_channel}")

    async with browser_session(
        proxy_info=proxy_info,
        browser_channel=browser_channel,
        browser_backend=browser_backend,
        user_agent="",
    ) as (context, page):
        try:
            if not cf_data:
                # HTTP 阶段 1 失败，用浏览器重走阶段 1+2
                cf_data = await _browser_open_signin(
                    page=page,
                    email=email,
                    log=log,
                )
                if not cf_data:
                    log("[混合] ❌ 阶段 1 失败")
                    return None

                reg_result = await _http_register(
                    email=email,
                    password=password,
                    cf_data=cf_data,
                    proxy_server=proxy_server,
                    solve_captcha_fn=solve_captcha_fn,
                    log=log,
                )
                if not reg_result:
                    log("[混合] ❌ 阶段 2 失败")
                    return None

                new_key = reg_result.get("key") or ""
                resp_cookies = reg_result.get("cookies") or {}

            # 阶段 3b: 浏览器完成 OTP + consent + API Key
            apikey = await _browser_otp_and_apikey(
                page=page,
                context=context,
                email=email,
                password=password,
                new_key=new_key,
                resp_cookies=resp_cookies,
                client_id=cf_data["client_id"],
                wait_code_fn=wait_code_fn,
                wait_link_fn=wait_link_fn,
                log=log,
            )

            if not apikey:
                log("[混合] ❌ 阶段 3 未拿到 API Key")
                return {
                    "apikey": None,
                    "email": email,
                    "key": new_key,
                    "status": "partial_registered",
                    "error": "OTP/API Key 阶段未完成（账号已注册但未拿到 key）",
                }

            return {
                "apikey": apikey,
                "email": email,
                "key": new_key,
                "status": "ok",
            }

        except Exception as exc:
            log(f"[混合] ❌ 异常: {exc}")
            import traceback
            traceback.print_exc()
            return None
