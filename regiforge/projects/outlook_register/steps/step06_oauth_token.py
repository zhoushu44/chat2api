"""step06：注册成功后跑 Public Client OAuth 拿 refresh_token。

写入 `AccountResult.extra`：
  - refresh_token   outlookEmailPlus 导入必需
  - access_token    短期有效，可选
  - client_id       Azure 应用 ID（= project_cfg.oauth_client_id）
  - tenant          consumers / common
  - scope           注册时实际用的 scope
  - expires_in      access_token 有效期（秒）

参考实现：daimon3332/OutlookRegister 的 controllers/oauth2.py + Outlook-Oauth-GetToken。
"""
from __future__ import annotations

import asyncio
import time
import urllib.parse
from typing import Any

import requests


def _build_authorize_url(
    *,
    client_id: str,
    tenant: str,
    scope: str,
    redirect_uri: str,
    state: str = "regiforge_outlook_oauth",
) -> str:
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "response_mode": "query",
        "scope": scope,
        "state": state,
        "prompt": "select_account",
    }
    qs = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize?{qs}"


async def _capture_authorization_code(
    page: Any,
    ctx: Any,
    *,
    authorize_url: str,
    redirect_uri: str,
    account_email: str,
    timeout: float,
) -> str:
    """跳到 authorize 等用户同意，捕获跳回 redirect_uri 的 code。

    监听 page.on("request") 拦截跳到 redirect_uri 的导航，从 query 抽 code。
    """
    target = urllib.parse.urlparse(redirect_uri)
    target_host = target.netloc
    target_path = target.path or "/"

    captured: dict[str, str] = {}

    def _on_request(req: Any) -> None:
        try:
            url = req.url
        except Exception:
            return
        if not url.startswith("http"):
            return
        parsed = urllib.parse.urlparse(url)
        if parsed.netloc != target_host:
            return
        if not parsed.path.startswith(target_path):
            return
        qs = urllib.parse.parse_qs(parsed.query)
        if "code" in qs and qs["code"]:
            captured["code"] = qs["code"][0]

    page.on("request", _on_request)

    # 尝试 goto authorize URL，如果 ERR_ABORTED（常见于 fido 页面残留）则新 tab 重试
    for attempt in range(2):
        try:
            await page.goto(authorize_url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
            break
        except Exception as e:
            err_str = str(e)
            if "ERR_ABORTED" in err_str and attempt == 0:
                ctx.log("OAuth: goto 被 ABORTED，新 tab 重试")
                try:
                    page.remove_listener("request", _on_request)
                except Exception:
                    pass
                # 异步 Playwright：new_page() 返回 coroutine；需 await 才能拿到 Page
                page = await page.context.new_page()
                page.on("request", _on_request)
                continue
            raise

    # 等用户同意页 + 跳回；某些场景下会弹「是否允许此应用访问你的数据」 consent 页
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if captured.get("code"):
                return captured["code"]
            # prompt=select_account 会停在账号选择页，先选择本次注册账号。
            try:
                if (await page.title()).strip() in {"选择帐户", "Choose an account"}:
                    account = page.get_by_text(account_email, exact=True).first
                    if await account.count() > 0 and await account.is_visible():
                        ctx.log(f"OAuth account: 选择 {account_email}")
                        await account.click()
                        await page.wait_for_timeout(1000)
                        continue
            except Exception:
                pass
            # Microsoft 可能要求额外的身份验证；该页面需要人工完成，不能继续等 code。
            try:
                current_url = page.url or ""
                title = (await page.title()).strip()
                if "/proofs/Verify" in current_url or "保护过度" in title:
                    ctx.log(
                        "OAuth 触发 Microsoft 二次安全验证，当前账号无法自动获取 authorization code"
                    )
                    raise RuntimeError(
                        "OAuth 触发 Microsoft 二次安全验证（proofs/Verify），需要人工验证"
                    )
            except RuntimeError:
                raise
            except Exception:
                pass
            # Microsoft consent 页可能用 button，也可能用 input[type=submit]。
            try:
                for label in ["接受", "Allow", "Accept", "同意"]:
                    btn = page.get_by_role("button", name=label).first
                    if await btn.count() == 0:
                        btn = page.locator(f'input[type="submit"][value="{label}"]').first
                    if await btn.count() > 0 and await btn.is_visible():
                        ctx.log(f"OAuth consent: 点击「{label}」")
                        await btn.click()
                        break
            except Exception:
                pass
            await page.wait_for_timeout(800)
        raise TimeoutError(f"OAuth authorize 阶段未在 {int(timeout)}s 内捕获到 authorization code")
    finally:
        try:
            page.remove_listener("request", _on_request)
        except Exception:
            pass


def _exchange_code_for_tokens(
    *,
    client_id: str,
    tenant: str,
    scope: str,
    redirect_uri: str,
    code: str,
    timeout: float = 30,
) -> dict[str, Any]:
    """POST /token，换 access_token + refresh_token。"""
    url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    body = {
        "client_id": client_id,
        "scope": scope,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    resp = requests.post(url, data=body, timeout=timeout)
    try:
        payload = resp.json()
    except Exception as exc:
        raise RuntimeError(
            f"token 端点返回非 JSON: status={resp.status_code} body={resp.text[:200]} ({exc})"
        )
    if resp.status_code != 200 or "refresh_token" not in payload:
        err = payload.get("error_description") or payload.get("error") or payload
        raise RuntimeError(f"OAuth token 兑换失败: {err}")
    return payload


async def _dismiss_passkey_page(page: Any, ctx: Any) -> None:
    """step05 跳完后可能停在 Passkey 创建页（/fido/create），尝试跳过。

    如果跳过失败则导航到 about:blank，确保后续 goto authorize URL 不被 ABORTED。
    """
    try:
        title = (await page.title()).strip()
        url = page.url or ""
        if "/fido/create" not in url and "/interrupt/passkey" not in url and "passkey" not in title.lower() and "密钥" not in title:
            return
        ctx.log("OAuth: 检测到 Passkey 创建页，尝试跳过")
        for label in ["跳过", "Skip", "以后再说", "Not now", "取消", "Cancel"]:
            btn = page.get_by_role("button", name=label).first
            if await btn.count() == 0:
                btn = page.get_by_role("link", name=label).first
            if await btn.count() == 0:
                btn = page.locator(f'a:has-text("{label}")').first
            if await btn.count() > 0 and await btn.is_visible():
                ctx.log(f"OAuth Passkey: 点击「{label}」")
                await btn.click()
                await page.wait_for_timeout(2000)
                # 检查是否还在 fido 页
                if "/fido/create" not in (page.url or "") and "/interrupt/passkey" not in (page.url or ""):
                    return
        # 跳过按钮没找到或点击后仍停留 →导航到空白页
        ctx.log("OAuth Passkey: 未跳离 fido 页，导航到 about:blank")
        await page.goto("about:blank", wait_until="domcontentloaded", timeout=15000)
    except Exception as e:
        ctx.log(f"OAuth Passkey: 跳过失败（{e}），尝试导航到 about:blank")
        try:
            await page.goto("about:blank", wait_until="domcontentloaded", timeout=15000)
        except Exception:
            pass


async def run(
    page: Any,
    ctx: Any,
    *,
    client_id: str,
    redirect_uri: str,
    tenant: str,
    scope: str,
    account_email: str,
    timeout: float = 180,
) -> dict[str, Any]:
    """跑完整 OAuth 流程，返回 token dict（含 refresh_token / access_token / expires_in / scope）。"""
    if not client_id:
        raise RuntimeError("oauth_client_id 未配置（projects.outlook_register.oauth_client_id）")
    if not redirect_uri:
        raise RuntimeError("oauth_redirect_uri 未配置")

    await _dismiss_passkey_page(page, ctx)

    authorize_url = _build_authorize_url(
        client_id=client_id,
        tenant=tenant or "consumers",
        scope=scope or "offline_access https://graph.microsoft.com/Mail.Read",
        redirect_uri=redirect_uri,
    )
    ctx.log(f"OAuth authorize -> {authorize_url[:160]}")

    # 如果当前 page 仍在 fido 页面导致 goto 被 ABORTED，
    # 尝试用新 tab 打开 authorize URL
    try:
        current_url = page.url or ""
        if "/fido/create" in current_url or "/interrupt/passkey" in current_url:
            ctx.log("OAuth: 当前 page 仍停在 fido 页，尝试新 tab")
            new_page = page.context.pages[-1] if page.context.pages else page.context.new_page()
            code = await _capture_authorization_code(
                new_page,
                ctx,
                authorize_url=authorize_url,
                redirect_uri=redirect_uri,
                account_email=account_email,
                timeout=timeout,
            )
        else:
            code = await _capture_authorization_code(
                page,
                ctx,
                authorize_url=authorize_url,
                redirect_uri=redirect_uri,
                account_email=account_email,
                timeout=timeout,
            )
    except Exception:
        code = await _capture_authorization_code(
            page,
            ctx,
            authorize_url=authorize_url,
            redirect_uri=redirect_uri,
            account_email=account_email,
            timeout=timeout,
        )
    ctx.log(f"OAuth code 捕获成功（len={len(code)}），兑换 token")
    tokens = await asyncio.to_thread(
        _exchange_code_for_tokens,
        client_id=client_id,
        tenant=tenant or "consumers",
        scope=scope or "offline_access https://graph.microsoft.com/Mail.Read",
        redirect_uri=redirect_uri,
        code=code,
    )
    ctx.log(
        f"OAuth token 兑换成功: refresh_token={len(tokens.get('refresh_token', ''))}B, "
        f"access_token={len(tokens.get('access_token', ''))}B, expires_in={tokens.get('expires_in')}"
    )
    return tokens
