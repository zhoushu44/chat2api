"""D 段探索：OpenAI 密码+TOTP 协议登录。

关键点（比注册流程简单）：
- 不需要 Sentinel PoW（登录走密码+MFA，不是注册风控）
- 需要一个能过 Cloudflare 的浏览器拿 CF cookie，供 curl 后续复用
- 落地页是 /log-in（不是 /create-account）

用法：
    python regiforge/scripts/probe_login.py --step cfcookie|csrf|signin|password|mfa
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import struct
import sys
import time
import uuid
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import curl_cffi  # noqa: E402
from core.models import ProxyInfo  # noqa: E402

CHAT_BASE = "https://chatgpt.com"
AUTH_BASE = "https://auth.openai.com"
CLIENT_ID = "app_X8zY6vW2pQ9tR3dE7nK1jL5gH"  # ChatGPT web
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def totp_now(secret_b32: str) -> str:
    s = secret_b32.upper().replace(" ", "").rstrip("=")
    key = base64.b32decode(s)
    digest = hmac.new(key, struct.pack(">Q", int(time.time()) // 30), hashlib.sha1).digest()
    o = digest[-1] & 0x0F
    code = (int.from_bytes(digest[o:o + 4], "big") & 0x7FFFFFFF) % 1000000
    return f"{code:06d}"


async def browser_warmup(proxy_browser: str | None) -> dict:
    """用真 Chrome 过 CF，拿 cookie（登录不需要 sentinel token）。"""
    from playwright.async_api import async_playwright

    launch: dict = {
        "headless": True,
        "args": ["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    }
    chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if Path(chrome).exists():
        launch["executable_path"] = chrome
    else:
        launch["channel"] = "chrome"
    if proxy_browser:
        launch["proxy"] = {"server": proxy_browser}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(**launch)
        ctx = await browser.new_context(user_agent=DEFAULT_UA, locale="en-US")
        page = await ctx.new_page()
        try:
            await page.goto(f"{CHAT_BASE}/api/auth/csrf", wait_until="domcontentloaded", timeout=30_000)
            try:
                await page.wait_for_load_state("networkidle", timeout=8_000)
            except Exception:
                pass
            await page.goto(f"{AUTH_BASE}/log-in", wait_until="domcontentloaded", timeout=30_000)
            try:
                await page.wait_for_load_state("networkidle", timeout=8_000)
            except Exception:
                pass
        except Exception as exc:
            print(f"    [警告] 预热导航异常: {str(exc)[:150]}")
        cookies = await ctx.cookies()
        body = ""
        try:
            body = (await page.content())[:400]
        except Exception:
            pass
        url = page.url
        await browser.close()
    return {
        "cookie_str": "; ".join(f"{c['name']}={c['value']}" for c in cookies),
        "url": url,
        "names": [c["name"] for c in cookies],
        "body": body,
    }


def _set_cookies(session, cookie_str: str) -> None:
    for part in (cookie_str or "").split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        name, _, value = part.partition("=")
        for dom in ("chatgpt.com", ".chatgpt.com", ".openai.com", "auth.openai.com", ".auth.openai.com"):
            try:
                session.cookies.set(name.strip(), value.strip(), domain=dom)
            except Exception:
                pass


def _req(session, method: str, url: str, *, retries: int = 3, **kw):
    """带 TLS 瞬断重试的请求（对齐项目 _TlsRetrySession 思路）。

    curl 代理链路偶发 (35) TLS connect error / OPENSSL_internal，原 session 重试即可。
    """
    last = None
    for i in range(retries):
        try:
            return session.request(method, url, **kw)
        except Exception as exc:
            msg = str(exc).lower()
            last = exc
            if any(k in msg for k in ("tls connect error", "openssl_internal", "curl: (35)", "sslerror")):
                print(f"      [TLS 瞬断，1.5s 后重试 {i+1}/{retries}]", flush=True)
                time.sleep(1.5 * (i + 1))
                continue
            raise
    raise last  # type: ignore[misc]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--totp", required=True)
    ap.add_argument("--step", default="full")
    ap.add_argument("--proxy", default="")
    args = ap.parse_args()

    px = args.proxy or None
    px_browser = px.replace("socks5h://", "socks5://") if px else None
    proxies = {"http": px, "https": px} if px else None
    print(f"[TOTP] code={totp_now(args.totp)}", flush=True)

    # [1] 浏览器过 CF
    print("\n[1] 浏览器预热（过 CF 拿 cookie）...", flush=True)
    warm = asyncio.run(browser_warmup(px_browser))
    print(f"    url={warm['url'][:120]}", flush=True)
    print(f"    cookies={warm['names']}", flush=True)

    session = curl_cffi.requests.Session()
    _set_cookies(session, warm["cookie_str"])

    common = {"impersonate": "chrome131", "proxies": proxies, "timeout": 45}
    hdr = {
        "User-Agent": DEFAULT_UA,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "application/json",
    }

    if args.step == "cfcookie":
        return 0

    # [2] CSRF
    print("\n[2] GET /api/auth/csrf ...", flush=True)
    r = _req(session, "GET",
        f"{CHAT_BASE}/api/auth/csrf",
        headers={**hdr, "Referer": f"{CHAT_BASE}/auth/login"},
        **common,
    )
    print(f"    status={r.status_code} cf={r.headers.get('cf-mitigated','')}", flush=True)
    csrf = ""
    try:
        csrf = r.json().get("csrfToken", "")
    except Exception:
        pass
    print(f"    csrf_len={len(csrf)}", flush=True)
    if args.step == "csrf":
        return 0
    if not csrf:
        print("    [错误] CSRF 为空", flush=True)
        return 1

    # [3] signin → authorize（不跟注册，直接看落地）
    print("\n[3] POST /api/auth/signin/openai (prompt=login) ...", flush=True)
    oai_did = str(uuid.uuid4())
    sp = {
        "prompt": "login",
        "ext-oai-did": oai_did,
        "auth_session_logging_id": str(uuid.uuid4()).replace("-", ""),
        "screen_hint": "login",
        "login_hint": args.email,
    }
    r = _req(session, "POST",
        f"{CHAT_BASE}/api/auth/signin/openai?" + "&".join(f"{k}={v}" for k, v in sp.items()),
        data={"csrfToken": csrf},
        allow_redirects=False,
        headers={
            **hdr,
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": CHAT_BASE,
            "Referer": f"{CHAT_BASE}/auth/login",
            "sec-fetch-mode": "navigate",
            "sec-fetch-dest": "document",
            "sec-fetch-site": "same-origin",
        },
        **common,
    )
    print(f"    status={r.status_code}", flush=True)
    loc = ""
    try:
        loc = r.json().get("url", "")
    except Exception:
        loc = r.headers.get("Location", "")
    print(f"    authorize={loc[:180]}", flush=True)
    if args.step == "signin":
        return 0
    if not loc:
        print("    [错误] 无 authorize URL", flush=True)
        return 1

    # [4] 跟随 authorize，落哪个页面
    print("\n[4] 跟随 authorize ...", flush=True)
    cur = loc
    nav = {
        **hdr,
        "Accept": "text/html,application/xhtml+xml",
        "Referer": f"{CHAT_BASE}/",
        "upgrade-insecure-requests": "1",
        "sec-fetch-mode": "navigate",
        "sec-fetch-dest": "document",
        "sec-fetch-site": "cross-site",
    }
    final = cur
    for hop in range(10):
        rr = _req(session, "GET", cur, headers=nav, allow_redirects=False, **common)
        nxt = rr.headers.get("Location", "")
        print(f"    hop{hop} {rr.status_code} {cur[:100]}", flush=True)
        if nxt:
            print(f"         -> {nxt[:140]}", flush=True)
        if not nxt or rr.status_code >= 400:
            final = cur
            break
        cur = nxt if nxt.startswith("http") else AUTH_BASE + nxt
        final = cur
        if any(x in cur for x in ("/log-in", "/email-verification", "/add-phone")):
            break
    print(f"    最终: {final[:150]}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
