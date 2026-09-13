"""OpenAI Sentinel Token 提取（改编自 oumiFree/sentinel.py）。

短生命周期浏览器会话：打开 authorize 页 → 注入/等待 SentinelSDK → 取 token/cookie。

2026-07 起 auth.openai.com 的 CSP 含 `script-src ... 'strict-dynamic' + nonce`，
页面里 `<script src=sentinel...>` 会被下载但不执行，导致 `window.SentinelSDK` 一直 undefined。
因此改为：经代理拉取 sdk.js 源码，在页面上下文 `eval` 注入（与成功路径兼容的兜底）。
"""
from __future__ import annotations

import asyncio
import re
import secrets
import uuid
from typing import Any
from urllib.parse import quote

from core.browser_runner import (
    BROWSER_BACKEND_PATCHRIGHT,
    get_async_playwright,
    normalize_browser_backend,
    _system_chrome_path,
)
from core.models import ProxyInfo

AUTH_BASE = "https://auth.openai.com"
SENTINEL_BACKEND_SDK = "https://sentinel.openai.com/backend-api/sentinel/sdk.js"
CHAT_WEB_CLIENT_ID = "app_X8zY6vW2pQ9tR3dE7nK1jL5gH"
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# ── 浏览器指纹版本对齐（方案 A）────────────────────────────────────
# UA 可配置（Web UI user_agent 字段）；TLS 指纹与 Client Hints 必须与 UA 声明
# 版本一致，否则被判定非浏览器。curl_cffi 0.15.0 支持的 chrome 版本见下表。
_IMPERSONATE_TABLE = (
    (146, "chrome146"), (145, "chrome145"), (142, "chrome142"), (136, "chrome136"),
    (133, "chrome133a"), (131, "chrome131"), (124, "chrome124"), (123, "chrome123"),
    (120, "chrome120"), (119, "chrome119"), (116, "chrome116"), (110, "chrome110"),
    (107, "chrome107"), (104, "chrome104"), (101, "chrome101"), (100, "chrome100"),
    (99, "chrome99"),
)
_DEFAULT_IMPERSONATE = "chrome131"


def impersonate_for_ua(ua: str) -> str:
    """按 UA 声明的大版本选最近的 curl_cffi chrome TLS 指纹，防止 TLS 与 UA 失配。"""
    m = re.search(r"\bChrome/(\d+)", ua or "")
    if not m:
        return _DEFAULT_IMPERSONATE
    major = int(m.group(1))
    for ver, name in _IMPERSONATE_TABLE:
        if ver <= major:
            return name
    return _DEFAULT_IMPERSONATE


def sec_ch_ua_for(ua: str) -> str:
    """按 UA 版本生成匹配的 sec-ch-ua 头（GREASE 值按版本区间取常见值）。"""
    m = re.search(r"\bChrome/(\d+)", ua or "")
    major = int(m.group(1)) if m else 131
    grease = '"Not/A)Brand";v="24"' if major >= 126 else '"Not/A)Brand";v="99"'
    return f'"Chromium";v="{major}", "Google Chrome";v="{major}", {grease}'


def _playwright_proxy(proxy_info: ProxyInfo | None) -> dict[str, str] | None:
    if not proxy_info or not proxy_info.server:
        return None
    return proxy_info.to_playwright()


def _curl_proxy_url(proxy_info: ProxyInfo | None) -> str | None:
    if not proxy_info or not proxy_info.server:
        return None
    server = proxy_info.server.strip()
    if server.startswith("socks5://"):
        server = "socks5h://" + server[len("socks5://") :]
    if proxy_info.username and proxy_info.password and "@" not in server.split("://", 1)[-1]:
        scheme, rest = server.split("://", 1)
        from urllib.parse import quote as q

        return f"{scheme}://{q(proxy_info.username, safe='')}:{q(proxy_info.password, safe='')}@{rest}"
    return server


def _fetch_text(
    url: str,
    *,
    proxy_url: str | None,
    user_agent: str,
    timeout: float = 30,
    impersonate: str | None = None,
) -> str:
    from curl_cffi import requests as creq

    kw: dict[str, Any] = {
        "timeout": timeout,
        # 与 UA 声明版本对齐的 TLS 指纹（方案 A/A+）
        "impersonate": impersonate or impersonate_for_ua(user_agent),
        "headers": {"User-Agent": user_agent, "Accept": "*/*", "Referer": f"{AUTH_BASE}/"},
    }
    if proxy_url:
        kw["proxy"] = proxy_url
    r = creq.get(url, **kw)
    if r.status_code >= 400:
        raise RuntimeError(f"下载 SDK 失败 {r.status_code}: {url}")
    text = r.text or ""
    if not text.strip():
        raise RuntimeError(f"下载 SDK 为空: {url}")
    return text


def _versioned_sdk_url(backend_js: str) -> str | None:
    m = re.search(
        r"https://sentinel\.openai\.com/sentinel/[A-Za-z0-9._-]+/sdk\.js",
        backend_js,
    )
    return m.group(0) if m else None


async def _page_diag(page: Any) -> dict[str, Any]:
    """采集失败诊断：是否 CF、脚本数、body 片段。"""
    info: dict[str, Any] = {"url": "", "title": "", "cf": False, "scripts": 0, "body": ""}
    try:
        info["url"] = page.url or ""
    except Exception:
        pass
    try:
        info["title"] = await page.title()
    except Exception:
        pass
    try:
        info.update(
            await page.evaluate(
                """() => {
                  const html = document.documentElement ? document.documentElement.outerHTML : '';
                  const body = (document.body && document.body.innerText) ? document.body.innerText : '';
                  const scripts = Array.from(document.scripts || []).map(s => s.src || s.type || 'inline');
                  const cf = /just a moment|cf-browser-verification|challenge-platform|cf-challenge|Attention Required/i.test(html + ' ' + body)
                    || /cloudflare/i.test(document.title || '');
                  return {
                    cf: !!cf,
                    scripts: scripts.length,
                    has_sentinel_script: scripts.some(s => /sentinel/i.test(String(s))),
                    sentinel_type: typeof window.SentinelSDK,
                    body: String(body || '').replace(/\\s+/g, ' ').slice(0, 220),
                  };
                }"""
            )
        )
    except Exception as exc:
        info["diag_error"] = str(exc)
    return info


async def _sdk_ready(page: Any) -> bool:
    try:
        return bool(
            await page.evaluate(
                """() => {
                  const s = window.SentinelSDK;
                  return !!(s && typeof s.init === 'function' && typeof s.token === 'function');
                }"""
            )
        )
    except Exception:
        return False


async def _inject_sdk_via_eval(
    page: Any,
    *,
    proxy_info: ProxyInfo | None,
    user_agent: str,
    impersonate: str | None = None,
    log: Any,
) -> bool:
    """CSP strict-dynamic 下页面 script 不执行时，eval 注入 backend + versioned SDK。"""
    proxy_url = _curl_proxy_url(proxy_info)
    try:
        backend_js = _fetch_text(
            SENTINEL_BACKEND_SDK, proxy_url=proxy_url, user_agent=user_agent,
            impersonate=impersonate,
        )
    except Exception as exc:
        log(f"Sentinel: 下载 backend sdk 失败: {exc}")
        return False

    versioned_url = _versioned_sdk_url(backend_js)
    if not versioned_url:
        log("Sentinel: backend sdk 中未解析到 versioned sdk URL")
        return False
    try:
        versioned_js = _fetch_text(
            versioned_url, proxy_url=proxy_url, user_agent=user_agent,
            impersonate=impersonate,
        )
    except Exception as exc:
        log(f"Sentinel: 下载 versioned sdk 失败: {exc}")
        return False

    log(
        f"Sentinel: CSP 兜底注入 sdk backend={len(backend_js)}B versioned={len(versioned_js)}B "
        f"url={versioned_url.split('/')[-2]}"
    )

    # 去掉 backend 里动态 appendChild(script) 的部分，改由我们直接 eval versioned
    backend_stub = re.sub(
        r"\(function\s*\(\)\s*\{[\s\S]*?appendChild\(script\);\s*\}\)\(\);\s*$",
        "",
        backend_js.strip(),
    )
    if not backend_stub:
        backend_stub = backend_js

    for label, code in (("backend", backend_stub), ("versioned", versioned_js)):
        res = await page.evaluate(
            """(code) => {
              try {
                (0, eval)(code);
                const s = window.SentinelSDK;
                return {
                  ok: true,
                  type: typeof s,
                  keys: s ? Object.keys(s) : null,
                  init_type: s && typeof s.init,
                  token_type: s && typeof s.token,
                };
              } catch (e) {
                return {ok: false, err: String(e), type: typeof window.SentinelSDK};
              }
            }""",
            code,
        )
        log(f"Sentinel: eval {label} -> {res}")
        if not res or not res.get("ok"):
            return False

    # versioned 可能异步接管 stub；稍等
    for _ in range(15):
        if await _sdk_ready(page):
            return True
        await page.wait_for_timeout(400)
    return await _sdk_ready(page)


async def extract_sentinel(
    *,
    proxy_info: ProxyInfo | None = None,
    user_agent: str = "",
    browser_backend: str = "playwright",
    log: Any | None = None,
    wait_seconds: float = 90,
    headless: bool = True,
    fingerprint: dict[str, Any] | None = None,
) -> dict[str, str]:
    """提取 Sentinel token 与相关 cookie。

    返回:
        sentinel_token / sentinel_so_token / cookie_str / oai_did

    fingerprint（可选）：A+ 随机指纹（_fingerprint.generate_fingerprint）。
    传入后浏览器 context 的 UA / locale / timezone / viewport / 硬件画像
    与 curl_cffi 侧完全一致，避免「浏览器画像 vs 请求画像」不一致。
    """
    fp = fingerprint

    def _log(msg: str) -> None:
        if log:
            log(msg)

    backend_id = normalize_browser_backend(browser_backend)
    chrome = _system_chrome_path()
    if not chrome and backend_id != BROWSER_BACKEND_PATCHRIGHT:
        raise RuntimeError("未找到 Google Chrome，HTTP 模式提取 Sentinel 需要系统 Chrome")

    ua = fp["user_agent"] if fp else ((user_agent or "").strip() or DEFAULT_UA)
    device_id = str(uuid.uuid4())
    state = secrets.token_urlsafe(32)
    scope = (
        "openid email profile offline_access model.request model.read "
        "organization.read organization.write"
    )
    auth_url = (
        f"{AUTH_BASE}/api/accounts/authorize"
        f"?client_id={CHAT_WEB_CLIENT_ID}"
        f"&scope={quote(scope)}"
        f"&response_type=code"
        f"&redirect_uri={quote('https://chatgpt.com/api/auth/callback/openai')}"
        f"&audience={quote('https://api.openai.com/v1')}"
        f"&device_id={device_id}"
        f"&prompt=login&screen_hint=signup&state={state}"
    )

    proxy = _playwright_proxy(proxy_info)
    _log(f"Sentinel: backend={backend_id} Chrome={chrome or 'channel=chrome'}")
    _log(f"Sentinel: proxy={proxy.get('server') if proxy else '直连'}")

    launch: dict[str, Any] = {
        "headless": bool(headless),
        "args": ["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    }
    # Patchright 优先 channel=chrome；其它底座优先系统 Chrome 路径
    if backend_id == BROWSER_BACKEND_PATCHRIGHT:
        launch["channel"] = "chrome"
    elif chrome:
        launch["executable_path"] = chrome
    else:
        launch["channel"] = "chrome"
    # A+：随机指纹时 context 画像与 curl 侧完全一致（语言/时区/视口）
    context_kwargs: dict[str, Any] = {
        "user_agent": ua,
        "viewport": fp["viewport"] if fp else {"width": 1280, "height": 800},
        "locale": fp["locale"] if fp else "en-US",
        "timezone_id": fp["timezone_id"] if fp else "America/New_York",
        "ignore_https_errors": True,
    }
    # A+：navigator 硬件画像注入（真实浏览器同会话固定，防关联）
    hw_js: str | None = None
    if fp:
        mem = fp.get("device_memory")
        mem_js = f"{mem}" if mem else "undefined"
        hw_js = (
            "(() => {"
            f"Object.defineProperty(navigator, 'hardwareConcurrency', {{get: () => {fp['hardware_concurrency']}}});"
            f"Object.defineProperty(navigator, 'deviceMemory', {{get: () => {mem_js}}});"
            f"Object.defineProperty(navigator, 'maxTouchPoints', {{get: () => {fp['max_touch_points']}}});"
            f"Object.defineProperty(navigator, 'platform', {{get: () => '{fp['navigator_platform']}'}});"
            f"Object.defineProperty(navigator, 'vendor', {{get: () => '{fp['navigator_vendor']}'}});"
            f"Object.defineProperty(window, 'devicePixelRatio', {{get: () => {fp['device_pixel_ratio']}}});"
            "})();"
        )
    if proxy:
        context_kwargs["proxy"] = proxy
        if proxy_info and proxy_info.server.lower().startswith("socks5://"):
            # 仅对非本机 SOCKS 强制远程 DNS；本地 bridge/manual 不要 MAP * ~NOTFOUND
            host = (proxy_info.server.split("://", 1)[-1].split("@")[-1].split(":")[0] or "").strip()
            if host and host not in {"127.0.0.1", "localhost"}:
                # EXCLUDE 代理服务器本身，否则 Chrome 把代理服务器也 MAP 成 ~NOTFOUND
                # 导致 ERR_PROXY_CONNECTION_FAILED
                launch["args"].append(
                    f"--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE {host}"
                )

    async with get_async_playwright(backend_id) as p:
        browser = await p.chromium.launch(**launch)
        try:
            ctx = await browser.new_context(**context_kwargs)
            if hw_js:
                await ctx.add_init_script(hw_js)
            page = await ctx.new_page()
            failed_assets: list[str] = []

            def _on_response(resp: Any) -> None:
                try:
                    url = resp.url or ""
                    if resp.status >= 400 and any(k in url for k in ("sentinel", "challenge", "cdn", "static")):
                        failed_assets.append(f"{resp.status}:{url[:120]}")
                except Exception:
                    pass

            page.on("response", _on_response)
            _log("Sentinel: 打开授权页...")
            try:
                await page.goto(auth_url, wait_until="domcontentloaded", timeout=45_000)
            except Exception as exc:
                _log(f"Sentinel: domcontentloaded 失败，改用 commit: {exc}")
                await page.goto(auth_url, wait_until="commit", timeout=45_000)

            try:
                await page.wait_for_load_state("networkidle", timeout=12_000)
            except Exception:
                pass

            # 先等页面自然加载（兼容旧环境）；超时后 CSP 兜底注入
            found = False
            natural_wait = min(20.0, max(6.0, wait_seconds * 0.25))
            natural_rounds = max(3, int(natural_wait / 2))
            for i in range(natural_rounds):
                if await _sdk_ready(page):
                    found = True
                    _log(f"Sentinel: 自然加载就绪 ({i * 2}s)")
                    break
                if i % 3 == 0:
                    diag = await _page_diag(page)
                    _log(
                        f"Sentinel: 等待 SDK... ({i * 2}s) type={diag.get('sentinel_type')} "
                        f"cf={diag.get('cf')} scripts={diag.get('scripts')} "
                        f"url={(diag.get('url') or page.url)[:80]}"
                    )
                await page.wait_for_timeout(2000)

            if not found:
                _log("Sentinel: 页面 script 未执行（疑似 CSP strict-dynamic），启用 eval 注入")
                found = await _inject_sdk_via_eval(
                    page,
                    proxy_info=proxy_info,
                    user_agent=ua,
                    impersonate=fp["impersonate"] if fp else None,
                    log=_log,
                )

            # 注入后再给一点时间
            if not found:
                extra_rounds = max(5, int(max(0.0, wait_seconds - natural_wait) / 2))
                for i in range(extra_rounds):
                    if await _sdk_ready(page):
                        found = True
                        break
                    if i % 5 == 0:
                        diag = await _page_diag(page)
                        _log(
                            f"Sentinel: 注入后等待... ({i * 2}s) type={diag.get('sentinel_type')} "
                            f"url={(diag.get('url') or page.url)[:80]}"
                        )
                    await page.wait_for_timeout(2000)

            if not found:
                diag = await _page_diag(page)
                asset_hint = ""
                if failed_assets:
                    asset_hint = " assets=" + " | ".join(failed_assets[:4])
                raise RuntimeError(
                    "SentinelSDK 未出现"
                    f"（cf={diag.get('cf')} scripts={diag.get('scripts')} "
                    f"has_sentinel_script={diag.get('has_sentinel_script')} "
                    f"type={diag.get('sentinel_type')}）"
                    f" title={diag.get('title')!r} url={diag.get('url') or page.url}"
                    f"{asset_hint}"
                    f" body~{diag.get('body')!r}"
                )

            _log("Sentinel: SDK ready，init + token...")
            try:
                await asyncio.wait_for(
                    page.evaluate(
                        """async () => {
                          if (window.SentinelSDK && typeof window.SentinelSDK.init === 'function') {
                            try { await window.SentinelSDK.init(); } catch (e) {}
                          }
                        }"""
                    ),
                    timeout=15.0,
                )
            except Exception as exc:
                _log(f"Sentinel: init 超时/异常（继续 token）: {exc}")
            await page.wait_for_timeout(1500)

            oai_did = await page.evaluate(
                "document.cookie.match(/oai-did=([^;]+)/)?.[1] || ''"
            )
            # token() 偶发挂起：JS 侧 Promise.race + asyncio.wait_for，避免整段注册卡死
            token_js = """async (args) => {
                const d = args.did;
                const flow = args.flow;
                const ms = args.ms || 20000;
                const withTimeout = (p, t) => Promise.race([
                  p,
                  new Promise((_, rej) => setTimeout(() => rej(new Error('token_timeout_' + t + 'ms')), t)),
                ]);
                const r = await withTimeout(SentinelSDK.token(), ms);
                if (flow === 'so') {
                  const raw = (typeof r === 'string') ? r : JSON.stringify(r);
                  let p = (typeof r === 'string') ? JSON.parse(r) : r;
                  return JSON.stringify({so: raw, c: p.c, id: d, flow: 'oauth_create_account'});
                }
                let p = (typeof r === 'string') ? JSON.parse(r) : r;
                p.id = d;
                p.flow = 'username_password_create';
                return JSON.stringify(p);
            }"""
            try:
                sentinel_token = await asyncio.wait_for(
                    page.evaluate(token_js, {"did": oai_did, "flow": "main", "ms": 25_000}),
                    timeout=30.0,
                )
            except Exception as exc:
                raise RuntimeError(f"Sentinel token() 失败/超时: {exc}") from exc
            try:
                sentinel_so = await asyncio.wait_for(
                    page.evaluate(token_js, {"did": oai_did, "flow": "so", "ms": 25_000}),
                    timeout=30.0,
                )
            except Exception as exc:
                _log(f"Sentinel: so-token 失败（可空）: {exc}")
                sentinel_so = ""
            # 访问 chatgpt.com：让真实浏览器通过 CF 挑战，取得 __cf_bm / cf_clearance，
            # 供后续 curl_cffi 调用 chatgpt.com /api/auth/csrf 复用（同 UA + 同代理出口 IP）。
            # 2026-08 起 /api/auth/csrf 对 curl_cffi 返回 cf-mitigated: challenge 403。
            try:
                await page.goto(
                    "https://chatgpt.com/api/auth/csrf",
                    wait_until="domcontentloaded",
                    timeout=20_000,
                )
                try:
                    await page.wait_for_load_state("networkidle", timeout=8_000)
                except Exception:
                    pass
                _log("Sentinel: 已预热 chatgpt.com（CF cookie）")
            except Exception as exc:
                _log(f"Sentinel: chatgpt.com 预热失败（不影响 token）: {str(exc)[:120]}")
            cookies = await ctx.cookies()
            cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
            if not sentinel_token:
                raise RuntimeError("Sentinel token 为空（SDK ready 但 token() 无结果）")
            _log(f"Sentinel: 提取成功 oai_did={str(oai_did)[:8]}... token_len={len(str(sentinel_token))}")
            return {
                "sentinel_token": str(sentinel_token or ""),
                "sentinel_so_token": str(sentinel_so or ""),
                "cookie_str": cookie_str,
                "oai_did": str(oai_did or device_id),
            }
        finally:
            await browser.close()
