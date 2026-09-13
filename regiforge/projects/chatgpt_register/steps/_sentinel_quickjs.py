# -*- coding: utf-8 -*-
"""QuickJS-driven Sentinel token generator（吸收 gpt-outlook-register v0.5.5）。

为什么要有这东西：
  纯 Python 合成 PoW 能过 OpenAI 的表面校验（/sentinel/req 200），但 OTP 派发服务
  会用真 sdk.js 在服务端深校验 token，合成的会过不去 → 邮件 silent-drop。
  要过，必须用 Node 子进程跑 OpenAI 真实 sdk.js（从 sentinel.openai.com 下载缓存），
  输出与真实浏览器同款 token。

实现：
  - 每次请求 spawn `node _openai_sentinel_quickjs.js`
  - wrapper 加载 sdk.js + 薄适配层（stdin/stdout 交换 requirements / solve）
  - 两遍：requirements → request_p，再 /sentinel/req 拿 challenge，再 solve → token
  - 服务端在 challenge 里说了算 SO token 是否必需（username_password_create 无 so 块）

公开 API：
  get_sentinel_token_via_quickjs(session, device_id, *, flow, ...) -> (token, so_token) | None
  网络类异常（TLS 瞬断）原样上抛，让外层 TLS 重试兜住；JS/PoW 类失败返回 None。
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

SENTINEL_VERSION = "20260219f9f6"
SENTINEL_SDK_URL = f"https://sentinel.openai.com/sentinel/{SENTINEL_VERSION}/sdk.js"
SENTINEL_REQ_URL = "https://sentinel.openai.com/backend-api/sentinel/req"

# TLS 握手瞬断标记（与 http_client 同口径，内联避免跨目录依赖）
_TLS_ERROR_MARKERS = ("curl: (35)", "tls connect error", "openssl_internal", "sslerror")


def _is_tls_handshake_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(m in msg for m in _TLS_ERROR_MARKERS)


def _resolve_node_binary() -> str:
    return (os.getenv("OPENAI_SENTINEL_NODE_PATH", "") or "").strip() or "node"


def _quickjs_script_path() -> Path:
    return Path(__file__).resolve().parent / "_openai_sentinel_quickjs.js"


_sdk_file_cache: Optional[Path] = None


def _ensure_sdk_file(session: Any, timeout_ms: int, proxy: str | None = None,
                     impersonate: str | None = None) -> Path:
    """下载 OpenAI 真实 sdk.js 到临时目录缓存（每版本一次）。"""
    global _sdk_file_cache
    if _sdk_file_cache and _sdk_file_cache.exists():
        return _sdk_file_cache

    cache_dir = Path(tempfile.gettempdir()) / "openai-sentinel-demo" / SENTINEL_VERSION
    cache_dir.mkdir(parents=True, exist_ok=True)
    sdk_file = cache_dir / "sdk.js"
    if sdk_file.exists() and sdk_file.stat().st_size > 0:
        _sdk_file_cache = sdk_file
        return sdk_file

    kw: dict[str, Any] = {
        "headers": {
            "accept": "*/*",
            "accept-language": "zh-CN,zh;q=0.9",
            "referer": "https://auth.openai.com/",
            "sec-fetch-dest": "script",
            "sec-fetch-mode": "no-cors",
            "sec-fetch-site": "same-site",
        },
        "timeout": max(10, int(timeout_ms / 1000)),
    }
    if proxy:
        kw["proxy"] = proxy
    if impersonate:
        kw["impersonate"] = impersonate
    resp = session.get(SENTINEL_SDK_URL, **kw)
    if getattr(resp, "status_code", 0) != 200:
        raise RuntimeError(f"下载 sdk.js 失败: HTTP {resp.status_code}")
    content = getattr(resp, "content", b"") or (resp.text or "").encode()
    if not content:
        raise RuntimeError("下载 sdk.js 失败: 响应为空")
    sdk_file.write_bytes(content)
    _sdk_file_cache = sdk_file
    return sdk_file


def _run_quickjs_action(
    *,
    action: str,
    sdk_file: Path,
    quickjs_script: Path,
    payload: dict,
    timeout_ms: int,
) -> dict:
    body = dict(payload)
    body["action"] = action
    proc = subprocess.run(
        [_resolve_node_binary(), str(quickjs_script)],
        input=json.dumps(body, ensure_ascii=False),
        text=True,
        capture_output=True,
        timeout=max(10, int(timeout_ms / 1000) + 5),
        env={
            **os.environ,
            "OPENAI_SENTINEL_SDK_FILE": str(sdk_file),
        },
    )
    if proc.returncode != 0:
        raise RuntimeError(f"QuickJS 执行失败: {(proc.stderr or proc.stdout or 'unknown').strip()[:300]}")
    out = (proc.stdout or "").strip()
    if not out:
        raise RuntimeError("QuickJS 返回空输出")
    data = json.loads(out)
    if not isinstance(data, dict):
        raise RuntimeError("QuickJS 输出不是 JSON 对象")
    return data


def _fetch_sentinel_challenge(
    session: Any,
    *,
    device_id: str,
    flow: str,
    request_p: str,
    timeout_ms: int,
    proxy: str | None = None,
    impersonate: str | None = None,
) -> dict:
    body = {"p": request_p, "id": device_id, "flow": flow}
    kw: dict[str, Any] = {
        "data": json.dumps(body, separators=(",", ":")),
        "headers": {
            "origin": "https://sentinel.openai.com",
            "referer": f"https://sentinel.openai.com/backend-api/sentinel/frame.html?sv={SENTINEL_VERSION}",
            "content-type": "text/plain;charset=UTF-8",
            "accept": "*/*",
            "accept-encoding": "gzip, deflate, br, zstd",
            "accept-language": "zh-CN,zh;q=0.9",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
        },
        "timeout": max(10, int(timeout_ms / 1000)),
    }
    if proxy:
        kw["proxy"] = proxy
    if impersonate:
        kw["impersonate"] = impersonate
    resp = session.post(SENTINEL_REQ_URL, **kw)
    if getattr(resp, "status_code", 0) != 200:
        raise RuntimeError(f"/sentinel/req HTTP {resp.status_code}")
    payload = resp.json()
    if not isinstance(payload, dict):
        raise RuntimeError("Sentinel challenge 响应不是 JSON 对象")
    return payload


def get_sentinel_token_via_quickjs(
    session: Any,
    device_id: str,
    *,
    flow: str = "authorize_continue",
    timeout_ms: int = 45000,
    log: Optional[Callable[[str], None]] = None,
    user_agent: str = "",
    screen: str = "",
    lang: str = "",
    lang_full: str = "",
    browser_type: str = "",
    platform: str = "",
    vendor: Optional[str] = None,
    hardware_concurrency: int = 0,
    device_memory: Optional[int] = None,
    max_touch_points: int = 0,
    device_pixel_ratio: float = 0.0,
    timezone: str = "",  # IANA 时区名（如 Asia/Tokyo）
    sec_ch_ua_full_version_list: str = "",
    sec_ch_ua_arch: str = "",
    sec_ch_ua_bitness: str = "",
    sec_ch_ua_model: str = "",
    sec_ch_ua_platform_version: str = "",
    proxy: str | None = None,
    impersonate: str | None = None,
) -> Optional[tuple[str, str]]:
    """QuickJS 路径。成功返回 (token, so_token)；JS/PoW 类失败返回 None；
    网络类异常（TLS 瞬断）原样上抛，由外层 _TlsRetrySession 兜住。

    指纹一致性：platform/vendor/hardware_concurrency 等按调用方传入的指纹喂给
    sdk.js 的 navigator，避免 UA 说 Windows Chrome 但 navigator 报 MacIntel。
    """
    log = log or (lambda m: logger.info(m))
    quickjs_script = _quickjs_script_path()
    if not quickjs_script.exists():
        log(f"Sentinel QuickJS 脚本不存在: {quickjs_script}")
        return None

    did = str(device_id or uuid.uuid4())

    screen_w, screen_h = "1920", "1080"
    if screen and "x" in screen:
        parts = screen.split("x", 1)
        screen_w, screen_h = parts[0], parts[1]

    lang_primary = lang or "en-US"
    languages = [lang_primary]
    if lang_full:
        for part in lang_full.split(","):
            tag = part.split(";")[0].strip()
            if tag and tag not in languages:
                languages.append(tag)

    ua_l = (user_agent or "").lower()
    if not platform:
        if "iphone" in ua_l:
            platform = "iPhone"
        elif "windows" in ua_l:
            platform = "Win32"
        elif "mac" in ua_l:
            platform = "MacIntel"
        else:
            platform = "Win32"
    if vendor is None:
        if "firefox" in ua_l:
            vendor = ""
        elif "chrome" in ua_l:
            vendor = "Google Inc."
        else:
            vendor = "Apple Computer, Inc."
    hw_conc = int(hardware_concurrency) if hardware_concurrency else 8

    env_payload = {
        "device_id": did,
        "user_agent": user_agent or "Mozilla/5.0",
        "screen_width": screen_w,
        "screen_height": screen_h,
        "language": lang_primary,
        "languages": languages,
        "platform": platform,
        "vendor": vendor,
        "hardware_concurrency": hw_conc,
        "browser_type": browser_type or "",
        "device_pixel_ratio": float(device_pixel_ratio) if device_pixel_ratio else 1.0,
        "max_touch_points": int(max_touch_points),
        "timezone": timezone or "UTC",
    }
    if device_memory is not None:
        env_payload["device_memory"] = int(device_memory)

    try:
        sdk_file = _ensure_sdk_file(session, timeout_ms, proxy=proxy, impersonate=impersonate)

        requirements = _run_quickjs_action(
            action="requirements",
            sdk_file=sdk_file,
            quickjs_script=quickjs_script,
            payload=env_payload,
            timeout_ms=timeout_ms,
        )
        request_p = str(requirements.get("request_p") or "").strip()
        if not request_p:
            log("Sentinel QuickJS 失败: requirements 未返回 request_p")
            return None

        challenge = _fetch_sentinel_challenge(
            session, device_id=did, flow=flow, request_p=request_p,
            timeout_ms=timeout_ms, proxy=proxy, impersonate=impersonate,
        )
        c_value = str(challenge.get("token") or "").strip()
        if not c_value:
            log("Sentinel QuickJS 失败: challenge token 为空")
            return None

        solve_payload = dict(env_payload)
        solve_payload.update({
            "request_p": request_p,
            "challenge": challenge,
            "flow": flow,
            "behavior_duration_ms": 4200,
        })
        solved = _run_quickjs_action(
            action="solve",
            sdk_file=sdk_file,
            quickjs_script=quickjs_script,
            payload=solve_payload,
            timeout_ms=timeout_ms,
        )

        so_token_raw = str(solved.get("so_token") or "").strip()
        # SO token 要不要由服务端在 challenge 里说了算（username_password_create 无 so 块）
        so_required = bool((challenge.get("so") or {}).get("required") is True)

        sdk_token = str(solved.get("token") or "").strip()
        if not sdk_token:
            log("Sentinel QuickJS 失败: SDK token 为空，中止以避免封号")
            return None
        if so_required and not so_token_raw:
            log("Sentinel QuickJS 失败: 服务端要求 SO token 但求解为空，中止以避免封号")
            return None
        log(f"Sentinel QuickJS OK (len={len(sdk_token)}, "
            f"so={'Y' if so_token_raw else 'N/A(服务端未要求)'})")
        return (sdk_token, so_token_raw)
    except Exception as e:
        if _is_tls_handshake_error(e):
            log(f"Sentinel 网络异常（非 PoW 问题，原样上抛）: {e}")
            raise
        log(f"Sentinel QuickJS 异常: {e}")
        return None
