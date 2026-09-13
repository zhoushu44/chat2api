"""D 段探索 v2：走 authorize 登录流程，抓全部 API 请求，导出页面 HTML。

思路：注册流程已验证 authorize URL 可用。这里用 screen_hint=login，
      落到真实登录页后抓网络请求（找密码/MFA 端点）+ 存 HTML 分析 DOM。

用法：
    python regiforge/scripts/probe_login_browser.py --step trace|fill
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import struct
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import quote

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

CHAT_BASE = "https://chatgpt.com"
AUTH_BASE = "https://auth.openai.com"
CLIENT_ID = "app_X8zY6vW2pQ9tR3dE7nK1jL5gH"
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
OUT = _ROOT / "data"


def totp_now(secret_b32: str) -> str:
    s = secret_b32.upper().replace(" ", "").rstrip("=")
    key = base64.b32decode(s)
    digest = hmac.new(key, struct.pack(">Q", int(time.time()) // 30), hashlib.sha1).digest()
    o = digest[-1] & 0x0F
    code = (int.from_bytes(digest[o:o + 4], "big") & 0x7FFFFFFF) % 1000000
    return f"{code:06d}"


def build_authorize(screen_hint: str) -> str:
    scope = (
        "openid email profile offline_access model.request model.read "
        "organization.read organization.write"
    )
    return (
        f"{AUTH_BASE}/api/accounts/authorize"
        f"?client_id={CLIENT_ID}"
        f"&scope={quote(scope)}"
        f"&response_type=code"
        f"&redirect_uri={quote('https://chatgpt.com/api/auth/callback/openai')}"
        f"&audience={quote('https://api.openai.com/v1')}"
        f"&device_id={uuid.uuid4()}"
        f"&prompt=login&screen_hint={screen_hint}&state={secrets.token_urlsafe(32)}"
    )


async def run(email: str, password: str, totp_secret: str, proxy: str | None, step: str) -> None:
    from playwright.async_api import async_playwright

    api_log: list[str] = []

    launch: dict = {
        "headless": True,
        "args": ["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    }
    chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if Path(chrome).exists():
        launch["executable_path"] = chrome
    else:
        launch["channel"] = "chrome"
    if proxy:
        launch["proxy"] = {"server": proxy}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(**launch)
        ctx = await browser.new_context(user_agent=DEFAULT_UA, locale="en-US")
        page = await ctx.new_page()

        def on_request(req):
            u = req.url
            if "oaistatic" in u or ".js" in u or ".css" in u or "image" in u:
                return
            if any(k in u for k in ("api/accounts", "backend-api", "oauth", "api/auth", "sentinel")):
                body = ""
                try:
                    if req.post_data:
                        body = " | body=" + str(req.post_data)[:200]
                except Exception:
                    pass
                line = f"{req.method} {u[:170]}{body}"
                api_log.append(line)

        page.on("request", on_request)
        print(f"[TOTP] code={totp_now(totp_secret)}\n", flush=True)

        # 从 chatgpt.com 的 NextAuth 发起登录（生成合法 state），再跟随 302 到 auth.openai.com
        print("[1] chatgpt.com -> POST /api/auth/signin/openai ...", flush=True)
        try:
            await page.goto(CHAT_BASE + "/", wait_until="domcontentloaded", timeout=60_000)
            await page.evaluate("""async () => {
                const r = await fetch('/api/auth/csrf', {credentials:'include'});
                const {csrfToken} = await r.json();
                const f = document.createElement('form');
                f.method = 'POST';
                f.action = '/api/auth/signin/openai';
                for (const [k, v] of Object.entries({
                    csrfToken: csrfToken,
                    callbackUrl: '/',
                })) {
                    const i = document.createElement('input');
                    i.type = 'hidden'; i.name = k; i.value = v;
                    f.appendChild(i);
                }
                document.body.appendChild(f);
                f.submit();
            }""")
            print("    已提交 signin 表单，等待跳转 ...", flush=True)
        except Exception as exc:
            print(f"    [警告] {str(exc)[:150]}", flush=True)

        # 等 SPA 渲染 / 跳转稳定
        for i in range(15):
            await page.wait_for_timeout(2000)
            n = 0
            for sel in ("input[type=email]", "input[type=password]", "input[name=password]"):
                try:
                    n += await page.locator(sel).count()
                except Exception:
                    pass
            if n:
                print(f"    渲染完成（{(i+1)*2}s）输入框={n}", flush=True)
                break
        print(f"    url={page.url[:150]}", flush=True)

        # 存 HTML
        try:
            html = await page.content()
            (OUT / "_probe_login_page.html").write_text(html, encoding="utf-8")
            print(f"    HTML={len(html)} chars", flush=True)
            print(f"    title={await page.title()}", flush=True)
        except Exception as exc:
            print(f"    [错误] {str(exc)[:140]}", flush=True)

        # locator 探测
        for sel in ("input[type=email]", "input[name=email]", "input#email",
                    "input[type=password]", "input[name=password]", "input#password",
                    "button[type=submit]", "button:has-text('Continue')", "button:has-text('Log in')",
                    "a[href*='log-in']", "a[href*='password']", "a:has-text('Log in')",
                    "a:has-text('password')"):
            try:
                n = await page.locator(sel).count()
                if n:
                    print(f"    locator {sel} -> {n}", flush=True)
            except Exception:
                pass

        if step == "fill":
            print("\n[2] 填邮箱 ...", flush=True)
            try:
                box = page.locator("input[type=email], input[name=email], input#email").first
                await box.fill(email, timeout=20_000)
                await page.wait_for_timeout(600)
                btn = page.locator("button[type=submit]").first
                await btn.click(timeout=20_000)
                print("    已提交邮箱", flush=True)
            except Exception as exc:
                print(f"    [错误] {str(exc)[:180]}", flush=True)
            for i in range(12):
                await page.wait_for_timeout(2000)
                n = await page.locator("input[type=password], input[name=password]").count()
                if n:
                    print(f"    密码页渲染（{(i+1)*2}s）", flush=True)
                    break
            print(f"    url={page.url[:150]}", flush=True)
            try:
                html = await page.content()
                (OUT / "_probe_password_page.html").write_text(html, encoding="utf-8")
                print(f"    密码页 HTML={len(html)} chars", flush=True)
            except Exception:
                pass
            for sel in ("input[type=password]", "input[name=password]", "input#password",
                        "input[inputmode=numeric]", "button[type=submit]"):
                try:
                    n = await page.locator(sel).count()
                    if n:
                        print(f"    locator {sel} -> {n}", flush=True)
                except Exception:
                    pass

            # 填密码
            print("\n[3] 填密码 ...", flush=True)
            try:
                pw = page.locator("input[type=password], input[name=password]").first
                await pw.fill(password, timeout=20_000)
                await page.wait_for_timeout(600)
                await page.locator("button[type=submit]").first.click(timeout=20_000)
                print("    已提交密码", flush=True)
            except Exception as exc:
                print(f"    [错误] {str(exc)[:180]}", flush=True)

            # 等 MFA 页（变化：出现数字输入 / 新 url）
            for i in range(15):
                await page.wait_for_timeout(2000)
                try:
                    u = page.url
                except Exception:
                    u = ""
                n = 0
                for sel in ("input[inputmode=numeric]", "input[name=code]", "input[autocomplete=one-time-code]"):
                    try:
                        n += await page.locator(sel).count()
                    except Exception:
                        pass
                if n or "mfa" in u.lower() or "totp" in u.lower() or "challenge" in u.lower():
                    print(f"    MFA 页出现（{(i+1)*2}s）code_box={n} url={u[:130]}", flush=True)
                    break
            print(f"    提交密码后 url={page.url[:150]}", flush=True)
            try:
                html = await page.content()
                (OUT / "_probe_mfa_page.html").write_text(html, encoding="utf-8")
                print(f"    MFA 页 HTML={len(html)} chars title={await page.title()}", flush=True)
            except Exception:
                pass
            for sel in ("input[inputmode=numeric]", "input[name=code]", "input[autocomplete=one-time-code]",
                        "input[type=text]", "button[type=submit]"):
                try:
                    n = await page.locator(sel).count()
                    if n:
                        print(f"    locator {sel} -> {n}", flush=True)
                except Exception:
                    pass

            # 填 TOTP 码（实时重算，避免过期）
            code = totp_now(totp_secret)
            print(f"\n[4] 填 TOTP code={code} ...", flush=True)
            try:
                boxes = page.locator("input[inputmode=numeric], input[name=code], input[autocomplete=one-time-code]")
                nb = await boxes.count()
                if nb > 1:
                    # 分格输入：逐格填 1 位
                    for idx, ch in enumerate(code):
                        if idx >= nb:
                            break
                        await boxes.nth(idx).fill(ch, timeout=10_000)
                        await page.wait_for_timeout(120)
                    print(f"    已逐格填入 {min(nb, len(code))} 位", flush=True)
                else:
                    await page.locator("input[name=code], input[inputmode=numeric]").first.fill(code, timeout=15_000)
                    print("    已填入整串", flush=True)
                await page.wait_for_timeout(800)
                await page.locator("button[type=submit]").first.click(timeout=20_000)
                print("    已提交 TOTP", flush=True)
            except Exception as exc:
                print(f"    [错误] TOTP: {str(exc)[:180]}", flush=True)

            # 等登录完成（离开 mfa-challenge 或到 chatgpt.com）
            for i in range(20):
                await page.wait_for_timeout(2000)
                u = page.url
                if "mfa-challenge" not in u:
                    print(f"    已离开 MFA（{(i+1)*2}s）url={u[:140]}", flush=True)
                    break
            print(f"    最终 url={page.url[:150]}", flush=True)
            try:
                print(f"    最终 title={await page.title()}", flush=True)
                html = await page.content()
                (OUT / "_probe_after_mfa.html").write_text(html, encoding="utf-8")
                print(f"    HTML={len(html)} chars", flush=True)
            except Exception:
                pass

            # 取 session / AT
            print("\n[5] 读 /api/auth/session ...", flush=True)
            try:
                sess = await page.evaluate("""async () => {
                    const r = await fetch('https://chatgpt.com/api/auth/session', {credentials:'include'});
                    const t = await r.text();
                    return {status: r.status, body: t.slice(0, 400)};
                }""")
                print(f"    session status={sess['status']}", flush=True)
                print(f"    body={sess['body'][:300]}", flush=True)
            except Exception as exc:
                print(f"    [错误] {str(exc)[:180]}", flush=True)

        print("\n[API 请求日志]", flush=True)
        for line in api_log[-40:]:
            print(f"    {line}", flush=True)

        await browser.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--totp", required=True)
    ap.add_argument("--proxy", default="")
    ap.add_argument("--step", default="trace")
    args = ap.parse_args()
    asyncio.run(run(args.email, args.password, args.totp, args.proxy or None, args.step))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
