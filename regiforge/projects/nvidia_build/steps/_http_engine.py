"""NVIDIA Build HTTP 注册引擎 — 纯协议注册（无需浏览器）。

流程：
  1. Bootstrap：GET build.nvidia.com 获取元数据
  2. 输入邮箱 → 进入密码页
  3. 输入密码 + 确认密码 + 同意条款
  4. hCaptcha：ctx.captcha 解题 + 提交
  5. 邮箱 OTP：ctx.email 收码 + 提交
  6. 登录 → 获取 API Key（NGC API）

注意：
  - 邮箱/代理/验证码走 Provider，不在本文件实现
  - 需要 curl_cffi 支持
"""
from __future__ import annotations

import asyncio
import os
import re
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

# ── curl_cffi transport ──────────────────────────────────────────────────

try:
    from curl_cffi import requests as cc_requests
    _HAS_CURL_CFFI = True
except Exception:
    cc_requests = None
    _HAS_CURL_CFFI = False

# ── config constants ────────────────────────────────────────────────────

BUILD_BASE = "https://build.nvidia.com"
SIGNIN_URL = f"{BUILD_BASE}/?modal=signin"
NGC_BASE = "https://api.ngc.nvidia.com"

# NVIDIA 认证端点（根据 browser 模式分析）
NVGS_BASE = "https://login.nvidia.com"
CLOUDACCOUNTS_BASE = "https://cloudaccounts.nvidia.com"
CONSENT_BASE = "https://consent.nvidia.com"

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)

DEFAULT_IMPERSONATE = "chrome145"
DEFAULT_HTTP_VERSION = "v2"

# hCaptcha sitekey（从 browser 模式步骤 9 提取）
HCAPTCHA_SITEKEY = "042b0b36-8bec-465e-a529-7c52a1c8d7d5"

# 密码（从 _rpa.py 复用）
PASSWORD = "zs1236547."

# ── typed results ──────────────────────────────────────────────────────

LogFn = Callable[[str], None]
WaitCodeFn = Callable[[str, float], Awaitable[str | None]]
SolveCaptchaFn = Callable[[str, str], Awaitable[str | None]]


def _require_curl_cffi():
    if not _HAS_CURL_CFFI:
        raise RuntimeError("HTTP 注册模式需要 curl_cffi，请运行：pip install curl_cffi")
    return cc_requests


def _proxy_url(proxy_info) -> str | None:
    """转为 curl_cffi 可用的代理 URL。"""
    if not proxy_info or not (proxy_info.server or "").strip():
        return None
    server = proxy_info.server.strip()
    if "://" not in server:
        server = f"socks5h://{server}"
    if server.startswith("socks5://"):
        server = "socks5h://" + server[len("socks5://"):]
    return server


class NvHTTPClient:
    """NVIDIA HTTP 注册客户端（基于 browser 模式流程分析）。
    
    注意：
      - 此 HTTP 引擎为框架示例，实际 URL 和字段需抓包分析
      - 建议先用 browser 模式跑一次，观察网络请求
      - 更新此文件中的 URL、字段名、sitekey 等
    """

    def __init__(self, proxy: str | None = None, debug: bool = False):
        if not _HAS_CURL_CFFI:
            raise RuntimeError("curl_cffi 未安装")
        self.debug = debug
        self._session = cc_requests.Session(
            impersonate=DEFAULT_IMPERSONATE,
            http_version=DEFAULT_HTTP_VERSION,
        )
        if proxy:
            self._session.proxies = {"http": proxy, "https": proxy}

    def close(self):
        self._session.close()

    def _base_headers(self) -> Dict[str, str]:
        return {
            "user-agent": DEFAULT_UA,
            "accept": "application/json, text/html,application/xhtml+xml",
            "accept-language": "zh-CN,zh;q=0.9",
            "sec-ch-ua": '"Chromium";v="145", "Google Chrome";v="145"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        }

    def _log(self, msg: str):
        if self.debug:
            print(f"  [nv_http] {msg}")

    # ── step 1: load page ───────────────────────────────────────────────

    def load_signup_page(self) -> Tuple[int, str]:
        """加载 build.nvidia.com/?modal=signin"""
        headers = self._base_headers()
        headers.update({
            "sec-fetch-site": "none",
            "sec-fetch-mode": "navigate",
            "sec-fetch-dest": "document",
        })
        response = self._session.request(
            method="GET",
            url=SIGNIN_URL,
            headers=headers,
            allow_redirects=True,
        )
        # curl_cffi 返回 Response 对象
        status = response.status_code
        html = response.text
        if status >= 400:
            raise RuntimeError(f"build.nvidia.com 返回 HTTP {status}")
        return status, html

    # ── step 2: submit email → NVGS create-account ─────────────────────

    def submit_email(self, email: str) -> Tuple[bool, str, str]:
        """提交邮箱，跳转到 NVGS 注册页。
        
        Browser 模式观察（_flow.py step3）：
          - 填邮箱到 input[name='email']
          - 点 Next 按钮
          - build.nvidia.com 直接导航到 login.nvidia.com/v1/create-account?email=xxx&key=yyy
          - 邮箱已自动预填，无需再点 #loginNextButton
        
        HTTP 模式实现（简化版）：
          - 直接访问 NVGS create-account URL（不带 key 参数，测试是否能访问）
          - 如果返回 200，说明可以直接访问
          - 如果返回 403/302，说明需要 key 参数
        
        返回：(success, error_msg, redirect_url)
        """
        self._log(f"submit_email: {email}")
        
        # 简化实现：直接访问 NVGS create-account（不带 key 参数）
        # 观察是否可以直接访问
        redirect_url = f"{NVGS_BASE}/v1/create-account"
        
        try:
            headers = self._base_headers()
            headers["referer"] = SIGNIN_URL
            response = self._session.request(
                method="GET",
                url=redirect_url,
                headers=headers,
                allow_redirects=True,
            )
            status = response.status_code
            html = response.text
            
            self._log(f"NVGS create-account HTTP {status}")
            
            if status == 200:
                self._log("submit_email: 成功加载 NVGS create-account 页")
                return True, "", redirect_url
            elif status == 403:
                # 403 表示可能需要 key 或 Cookie
                self._log("submit_email: 403 - 可能需要 key 参数或 Cookie")
                return False, "NVGS 返回 403（需要 key 或 Cookie）", redirect_url
            elif status in (301, 302, 303):
                # 重定向
                location = response.headers.get("location", "")
                self._log(f"submit_email: 重定向到 {location}")
                return True, "", location
            else:
                return False, f"NVGS 返回 HTTP {status}", redirect_url
        except Exception as e:
            self._log(f"submit_email: 异常 - {e}")
            return False, f"submit_email 异常：{e}", redirect_url

    # ── step 3: submit registration form ───────────────────────────────

    def submit_registration(
        self,
        email: str,
        password: str,
        hcaptcha_response: str,
    ) -> Tuple[bool, str]:
        """提交注册表单（NVGS create-account 页）。
        
        Browser 模式观察（_flow.py steps 6-11）：
          - #registration_password: 密码输入框
          - 确认密码（前端校验，可能无独立字段）
          - #data_general_agreement: 同意条款 checkbox
          - [name="h-captcha-response"]: hCaptcha token
          - #register_button: 创建账户按钮
        
        HTTP 模式实现（简化版）：
          - 构造表单数据
          - POST 到 /v1/create-account
          - 检查是否跳转到 profile-complete
        
        返回：(success, error_msg)
        """
        self._log("submit_registration: 提交注册表单...")
        
        # 构造表单数据（根据 browser 模式代码分析）
        form_data = {
            "registration_password": password,
            "data_general_agreement": "on",
            "h-captcha-response": hcaptcha_response,
            # 注意：email 已预填，POST 时可能不需要
        }
        
        # 提交表单（POST 到当前 URL）
        try:
            headers = self._base_headers()
            headers["content-type"] = "application/x-www-form-urlencoded"
            headers["origin"] = NVGS_BASE
            headers["referer"] = f"{NVGS_BASE}/v1/create-account"
            
            response = self._session.request(
                method="POST",
                url=f"{NVGS_BASE}/v1/create-account",
                headers=headers,
                data=form_data,
                allow_redirects=True,
            )
            status = response.status_code
            html = response.text
            
            self._log(f"submit_registration: HTTP {status}")
            
            if status == 200:
                # 检查是否成功（可能返回 JSON 或 HTML）
                if "profile-complete" in html.lower() or "verify" in html.lower():
                    self._log("submit_registration: 成功，跳转到 profile-complete")
                    return True, ""
                else:
                    # 可能返回错误
                    error = self._extract_error_from_html(html)
                    if error:
                        return False, f"注册失败：{error}"
                    else:
                        self._log("submit_registration: 返回 200 但无法判断成功")
                        return True, ""
            elif status == 400:
                # 表单验证失败
                error = self._extract_error_from_html(html)
                return False, f"表单验证失败：{error or 'HTTP 400'}"
            elif status == 403:
                return False, "注册被拒绝（403）"
            else:
                return False, f"注册返回 HTTP {status}"
        except Exception as e:
            self._log(f"submit_registration: 异常 - {e}")
            return False, f"submit_registration 异常：{e}"
    
    def _extract_csrf_token(self) -> str | None:
        """从当前 session 的最后响应中提取 CSRF token。"""
        # 简化实现：暂不提取，实际需要从 HTML 的 meta 标签或 JS 变量中找
        # 示例：<meta name="csrf-token" content="xxx">
        # 或 window.__INITIAL_STATE__ = {csrf: "xxx"}
        return None
    
    def _extract_error_from_html(self, html: str) -> str | None:
        """从 HTML 中提取错误信息。"""
        import re
        # 尝试从 error div 中提取
        error_match = re.search(r'class="error[^"]*"[^>]*>([^<]+)', html, re.IGNORECASE)
        if error_match:
            return error_match.group(1).strip()
        # 尝试从 alert/role="alert" 中提取
        alert_match = re.search(r'role="alert"[^>]*>([^<]+)', html, re.IGNORECASE)
        if alert_match:
            return alert_match.group(1).strip()
        return None

    # ── step 4: submit OTP ─────────────────────────────────────────────

    def submit_otp(self, email: str, code: str) -> Tuple[bool, str]:
        """提交邮箱验证码（OTP）。
        
        Browser 模式观察（_flow.py step12）：
          - 在 profile-complete 页
          - OTP 输入框：input[maxlength='1']（6 个单格）
          - 提交按钮：Continue / Verify
          - 提交后跳转到 consent.nvidia.com
        
        HTTP 模式实现（简化版）：
          - POST 到 /v1/otp/verify
          - 检查是否跳转到 consent
        
        返回：(success, error_msg)
        """
        self._log(f"submit_otp: email={email[:10]}... code={code}")
        
        # 构造 OTP 提交数据
        otp_data = {
            "email": email,
            "code": code,
        }
        
        # 提交 OTP（假设 POST 到 /v1/otp/verify）
        try:
            headers = self._base_headers()
            headers["content-type"] = "application/x-www-form-urlencoded"
            headers["origin"] = NVGS_BASE
            headers["referer"] = f"{NVGS_BASE}/v1/profile-complete"
            
            response = self._session.request(
                method="POST",
                url=f"{NVGS_BASE}/v1/otp/verify",
                headers=headers,
                data=otp_data,
                allow_redirects=True,
            )
            status = response.status_code
            html = response.text
            
            self._log(f"submit_otp: HTTP {status}")
            
            if status == 200:
                # 检查是否成功（跳转到 consent 或包含 success）
                if "consent" in html.lower() or "success" in html.lower():
                    self._log("submit_otp: 成功，跳转到 consent 页")
                    return True, ""
                else:
                    # 可能返回错误
                    error = self._extract_error_from_html(html)
                    if error:
                        return False, f"OTP 验证失败：{error}"
                    else:
                        self._log("submit_otp: 返回 200 但无法判断成功")
                        return True, ""
            elif status == 400:
                # OTP 错误或过期
                error = self._extract_error_from_html(html)
                return False, f"OTP 无效：{error or 'HTTP 400'}"
            elif status == 403:
                return False, "OTP 验证被拒绝（403）"
            else:
                return False, f"OTP 验证返回 HTTP {status}"
        except Exception as e:
            self._log(f"submit_otp: 异常 - {e}")
            return False, f"submit_otp 异常：{e}"

    # ── step 5: handle post-verification (consent / login / select-account) ──

    def handle_post_verification(self, email: str, password: str) -> Tuple[bool, str]:
        """处理验证后的流程：consent 页 → 密码登录 → select-account → build.nvidia.com。
        
        Browser 模式观察（_flow.py step13）：
          1. consent.nvidia.com: 勾选同意条款 checkbox → 点 Accept
          2. login.nvidia.com/login/password: 填邮箱 + Next → 填密码 + Sign In
          3. cloudaccounts.nvidia.com/select-account: 输入云账户名称 "11" → 点 Create
          4. 回调到 build.nvidia.com
        
        HTTP 模式实现（简化版）：
          由于涉及多域跳转和复杂的 Cookie/Session 管理，
          纯 HTTP 模式实现极其复杂。建议：
          - 方案 A: 用 browser 模式处理此部分（混合模式）
          - 方案 B: 模拟整个流程（需要大量抓包分析）
        
        这里提供方案 B 的框架实现（需要实际抓包验证）：
        
        返回：(success, error_msg)
        """
        self._log("handle_post_verification: 开始处理 consent → login → select-account")
        
        try:
            # 1. 处理 consent 页
            self._log("  [1/4] 处理 consent 页...")
            if not self._handle_consent():
                return False, "consent 处理失败"
            
            # 2. 密码登录
            self._log("  [2/4] 密码登录...")
            if not self._login_password(email, password):
                return False, "密码登录失败"
            
            # 3. 创建云账户（select-account）
            self._log("  [3/4] 创建云账户...")
            if not self._create_cloud_account():
                return False, "创建云账户失败"
            
            # 4. 回调到 build.nvidia.com
            self._log("  [4/4] 回调到 build.nvidia.com...")
            if not self._callback_to_build():
                return False, "回调失败"
            
            self._log("post_verification: 完成")
            return True, ""
        except Exception as e:
            self._log(f"post_verification: 异常 - {e}")
            return False, str(e)
    
    def _handle_consent(self) -> bool:
        """处理 consent 页：勾选同意条款 → 点 Accept。"""
        # 简化实现：访问 consent 页，模拟勾选和提交
        # 实际需要分析 consent 页的表单结构和提交端点
        try:
            # 访问 consent 页（OTP 后会自动跳转）
            # 检查当前 URL 是否在 consent 域
            if "consent" not in (self._session.cookies.get("domain") or ""):
                # 尝试访问 consent 页
                headers = self._base_headers()
                status, _, _, _ = self._session.request(
                    method="GET",
                    url=f"{CONSENT_BASE}/",
                    headers=headers,
                    allow_redirects=True,
                )
                self._log(f"consent 页 HTTP {status}")
            
            # 勾选同意条款并提交
            # 实际需要从 HTML 中提取表单字段并 POST
            # 简化：假设自动跳转
            return True
        except Exception as e:
            self._log(f"consent 处理异常：{e}")
            return False
    
    def _login_password(self, email: str, password: str) -> bool:
        """密码登录：填邮箱 + Next → 填密码 + Sign In。"""
        try:
            # 1. 访问登录页
            headers = self._base_headers()
            headers.update({
                "content-type": "application/x-www-form-urlencoded",
            })
            
            # identifier 页：填邮箱 + Next
            identifier_data = {"email": email}
            status, _, _, _ = self._session.request(
                method="POST",
                url=f"{NVGS_BASE}/v1/login/identifier",
                headers=headers,
                data=identifier_data,
                allow_redirects=False,
            )
            self._log(f"identifier HTTP {status}")
            
            # password 页：填密码 + Sign In
            password_data = {
                "email": email,
                "password": password,
            }
            response = self._session.request(
                method="POST",
                url=f"{NVGS_BASE}/v1/login/password",
                headers=headers,
                data=password_data,
                allow_redirects=False,
            )
            status = response.status_code
            self._log(f"password HTTP {status}")
            
            # 检查是否登录成功（302 跳转或 200 成功）
            if status in (200, 302, 303):
                return True
            else:
                body = response.text
                error = self._extract_error_from_html(body) or f"HTTP {status}"
                self._log(f"密码登录失败：{error}")
                return False
        except Exception as e:
            self._log(f"密码登录异常：{e}")
            return False
    
    def _create_cloud_account(self) -> bool:
        """创建云账户（select-account 页）。"""
        try:
            # 访问 cloudaccounts 页
            headers = self._base_headers()
            headers.update({
                "content-type": "application/json",
            })
            
            # 创建云账户（名称："11"）
            account_data = {"name": "11"}
            response = self._session.request(
                method="POST",
                url=f"{CLOUDACCOUNTS_BASE}/api/v1/accounts",
                headers=headers,
                json=account_data,
                allow_redirects=False,
            )
            status = response.status_code
            self._log(f"cloudaccount HTTP {status}")
            
            if status in (200, 201, 302, 303):
                return True
            else:
                # 403 表示需要先登录，尝试 nca_picker 回调
                if status == 403:
                    self._log("cloudaccounts 403，尝试 nca_picker 回调...")
                    try:
                        self._session.request(
                            method="GET",
                            url=f"{NVGS_BASE}/callback/nca_picker",
                            headers=self._base_headers(),
                            allow_redirects=True,
                        )
                        return True
                    except Exception as e:
                        self._log(f"nca_picker 回调异常：{e}")
                return False
        except Exception as e:
            self._log(f"创建云账户异常：{e}")
            return False
    
    def _callback_to_build(self) -> bool:
        """回调到 build.nvidia.com。"""
        try:
            headers = self._base_headers()
            response = self._session.request(
                method="GET",
                url=BUILD_BASE,
                headers=headers,
                allow_redirects=True,
            )
            status = response.status_code
            self._log(f"build.nvidia.com HTTP {status}")
            return status == 200
        except Exception as e:
            self._log(f"回调异常：{e}")
            return False

    # ── step 6: fetch API key ──────────────────────────────────────────

    def fetch_api_key(self) -> Tuple[Optional[str], str]:
        """获取 API Key（NGC API）。
        
        两步流程：
          1. GET https://api.ngc.nvidia.com/user-context → 获取 orgName
          2. POST https://api.ngc.nvidia.com/v3/orgs/{orgName}/keys/type/AI_PLAYGROUNDS_KEY
        
        需要有效的 session cookie（来自前面的登录流程）。
        """
        headers = self._base_headers()
        headers.update({
            "content-type": "application/json",
            "origin": NGC_BASE,
            "referer": f"{BUILD_BASE}/",
        })

        # 1. 获取用户信息（orgName）
        response = self._session.request(
            method="GET",
            url=f"{NGC_BASE}/user-context",
            headers=headers,
        )
        status = response.status_code
        
        if status != 200:
            return None, f"user-context failed: HTTP {status}"

        try:
            data = response.text
            user_info = __import__("json").loads(data)
            org_name = user_info.get("orgName")
            if not org_name:
                return None, "未找到 orgName"
        except Exception as e:
            return None, f"解析 user-context 失败：{e}"

        # 2. 创建 API Key
        key_data = {
            "expiryDate": "2126-04-08T07:00:00Z",
            "name": "dev",
            "type": "AI_PLAYGROUNDS_KEY",
            "policies": [{
                "product": "nv-cloud-functions",
                "scopes": ["invoke_function"],
                "resources": [{"id": "*", "type": "account-functions"}]
            }]
        }

        response = self._session.request(
            method="POST",
            url=f"{NGC_BASE}/v3/orgs/{org_name}/keys/type/AI_PLAYGROUNDS_KEY",
            headers=headers,
            json=key_data,
        )
        status = response.status_code
        
        if status != 200:
            body = response.text[:200]
            return None, f"创建 key 失败：HTTP {status} {body}"

        try:
            result = __import__("json").loads(response.text)
            api_key = result.get("result", {}).get("apiKey", {}).get("value", "")
            if api_key:
                return api_key, ""
            else:
                return None, "apiKey.value 为空"
        except Exception as e:
            return None, f"解析 API 响应失败：{e}"


async def register_http(
    *,
    email: str,
    password: str,
    wait_code: WaitCodeFn,
    solve_captcha: SolveCaptchaFn,
    proxy_info=None,
    mail_timeout: float = 120.0,
    captcha_timeout: float = 180.0,
    log: LogFn | None = None,
) -> Dict[str, str]:
    """NVIDIA HTTP 注册入口（框架示例）。
    
    ⚠️ 重要提示：
      此 HTTP 引擎为框架示例，展示了如何从 browser 模式转换到 HTTP 模式。
      实际 URL 和字段需要抓包分析后填充。
      
    下一步：
      1. 用 browser 模式跑一次，观察网络请求
      2. 更新 submit_email() / submit_registration() / submit_otp() 的 URL 和字段
      3. 测试完整的注册流程
    
    返回：{"email": ..., "password": ..., "apikey": ..., "error": ...}
    """
    def _log(msg: str):
        if log:
            log(msg)

    _require_curl_cffi()
    proxy_url = _proxy_url(proxy_info)

    client = NvHTTPClient(proxy=proxy_url, debug=False)
    apikey = None
    error = ""

    try:
        _log("[HTTP 引擎提示] 此为框架示例，需要抓包分析后填充实际 URL 和字段")
        _log("[HTTP 引擎提示] 详见 projects/nvidia_build/HTTP_MODE.md")
        
        # 1. Bootstrap
        _log("[1/6] 加载注册页面...")
        t0 = time.time()
        status, html = client.load_signup_page()
        _log(f"  OK ({time.time() - t0:.1f}s)")

        # 2. 提交邮箱 → NVGS
        _log("[2/6] 提交邮箱...")
        t0 = time.time()
        success, err, redirect_url = client.submit_email(email)
        if not success:
            # 占位实现会返回错误，提示需要抓包
            raise RuntimeError(err)
        _log(f"  OK → {redirect_url[:60]} ({time.time() - t0:.1f}s)")

        # 3. 解 hCaptcha
        _log("[3/6] 解决 hCaptcha...")
        t0 = time.time()
        hcaptcha_token = await solve_captcha(sitekey=HCAPTCHA_SITEKEY, page_url=redirect_url or SIGNIN_URL)
        if not hcaptcha_token:
            raise RuntimeError("hCaptcha 解题失败")
        _log(f"  OK token_len={len(hcaptcha_token)} ({time.time() - t0:.1f}s)")

        # 4. 提交注册表单
        _log("[4/6] 创建账号...")
        t0 = time.time()
        success, err = client.submit_registration(
            email=email,
            password=password,
            hcaptcha_response=hcaptcha_token,
        )
        if not success:
            raise RuntimeError(err)
        _log(f"  OK ({time.time() - t0:.1f}s)")

        # 5. 等待 + 提交 OTP
        _log("[5/6] 等待邮箱验证码...")
        t0 = time.time()
        code = await wait_code(email, mail_timeout)
        if not code:
            raise RuntimeError(f"等待验证码超时（{mail_timeout}s）")
        _log(f"  验证码：{str(code)[:2]}**** ({time.time() - t0:.1f}s)")

        _log("[6/6] 验证邮箱 OTP...")
        t0 = time.time()
        success, err = client.submit_otp(email, code)
        if not success:
            raise RuntimeError(err)
        _log(f"  OK ({time.time() - t0:.1f}s)")

        # 7. 处理 post-verification 流程（consent / login / select-account）
        _log("[7/8] 处理验证后流程...")
        t0 = time.time()
        success, err = client.handle_post_verification(email, password)
        if not success:
            _log(f"[WARN] post_verification 部分失败：{err}，继续尝试获取 API Key")
        _log(f"  {'OK' if success else 'PARTIAL'} ({time.time() - t0:.1f}s)")
        
        # 8. 获取 API Key（需要前面的 session）
        _log("[8/8] 获取 API Key...")
        t0 = time.time()
        apikey, err = client.fetch_api_key()
        if not apikey:
            raise RuntimeError(f"获取 API Key 失败：{err}")
        _log(f"  OK apikey={apikey[:20]}... ({time.time() - t0:.1f}s)")

        return {
            "email": email,
            "password": password,
            "apikey": apikey,
            "error": "",
        }

    except Exception as exc:
        _log(f"ERROR: {exc}")
        return {
            "email": email,
            "password": password,
            "apikey": apikey or "",
            "error": str(exc),
        }
    finally:
        client.close()


# ── 兼容旧版接口（保留） ────────────────────────────────────────────────

PASSWORD = "zs1236547."


def generate_random_email(domain: str = "zhoushu.kdns.fr") -> str:
    """生成随机 8 位数字邮箱（保留兼容）。"""
    import random
    random_num = "".join(str(random.randint(0, 9)) for _ in range(8))
    return f"{random_num}@{domain}"
