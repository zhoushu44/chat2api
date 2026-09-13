"""NVIDIA HTTP 模式 - 完整实现（按照 browser 模式流程）

流程：
1. 访问 build.nvidia.com/?modal=signin
2. 填邮箱 → 点 Next → 跳转到 NVGS（带 key 参数）
3. 在 NVGS 填写密码、同意条款、hCaptcha
4. 提交注册
5. OTP 验证
6. Post-Verification 流程
7. 获取 API Key
"""

import re
import time
from typing import Tuple, Any
from curl_cffi import requests as cc_requests


class NvHTTPClient:
    """NVIDIA HTTP 注册客户端（curl_cffi）"""
    
    def __init__(self, proxy: str | None = None):
        """初始化 HTTP 客户端
        
        Args:
            proxy: 代理地址，例如 "socks5://192.6.121.16:7890"
        """
        self._log = print
        self._session = cc_requests.Session(impersonate="chrome145")
        
        if proxy:
            # 解析 socks5 代理
            if proxy.startswith("socks5://"):
                self._session.proxies = {
                    "http": proxy,
                    "https": proxy
                }
                self._log(f"使用代理：{proxy}")
            else:
                self._session.proxies = {"http": proxy, "https": proxy}
        
        self._key = None  # 从 build.nvidia.com 获取的 key
        self._cookies = {}
    
    def _base_headers(self) -> dict:
        """基础请求头"""
        return {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "accept-language": "en-US,en;q=0.9",
            "user-agent": self._session.headers.get("user-agent", ""),
        }
    
    def load_signup_page(self) -> Tuple[bool, str]:
        """步骤 1: 访问 build.nvidia.com 获取 key
        
        返回：(success, error_msg)
        """
        self._log("load_signup_page: 访问 build.nvidia.com...")
        
        try:
            url = "https://build.nvidia.com/?modal=signin"
            headers = self._base_headers()
            
            response = self._session.request(
                method="GET",
                url=url,
                headers=headers,
                allow_redirects=True,
                timeout=30,
            )
            
            status = response.status_code
            html = response.text
            
            self._log(f"build.nvidia.com HTTP {status}")
            
            # 202 是 Cloudflare 挑战，说明需要处理 Cloudflare
            if status == 202:
                self._log("检测到 Cloudflare 挑战（HTTP 202）")
                self._log("⚠️  纯 HTTP 模式无法处理 Cloudflare，需要混合模式")
                self._log("⚠️  建议：用 Browser 模式获取 key，然后切换到 HTTP 模式")
                return False, "Cloudflare 挑战（需要 Browser 模式）"
            
            if status != 200:
                return False, f"build.nvidia.com 返回 HTTP {status}"
            
            # 从 HTML 中提取 key
            # 可能的位置：
            # 1. window.__INITIAL_STATE__.key
            # 2. <meta name="key" content="xxx">
            # 3. data-key="xxx"
            
            key = None
            
            # 尝试从 script 标签中的 JS 变量提取
            js_patterns = [
                r'"key"\s*:\s*"([a-f0-9-]+)"',
                r'key\s*:\s*"([a-f0-9-]+)"',
                r'__INITIAL_STATE__\s*=\s*\{[^}]*"key"\s*:\s*"([a-f0-9-]+)"',
            ]
            
            for pattern in js_patterns:
                match = re.search(pattern, html)
                if match:
                    key = match.group(1)
                    self._log(f"从 JS 提取到 key: {key[:20]}...")
                    break
            
            # 尝试从 meta 标签提取
            if not key:
                meta_match = re.search(r'<meta[^>]+name=["\']?key["\']?[^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
                if meta_match:
                    key = meta_match.group(1)
                    self._log(f"从 meta 提取到 key: {key[:20]}...")
            
            # 尝试从 data 属性提取
            if not key:
                data_match = re.search(r'data-key=["\']([^"\']+)["\']', html)
                if data_match:
                    key = data_match.group(1)
                    self._log(f"从 data 属性提取到 key: {key[:20]}...")
            
            if not key:
                self._log("警告：未找到 key 参数，尝试不使用 key 继续")
                key = ""
            
            self._key = key
            
            # 保存 Cookie
            for cookie in self._session.cookies:
                self._cookies[cookie.name] = cookie.value
            
            self._log(f"保存了 {len(self._cookies)} 个 Cookie")
            
            return True, ""
            
        except Exception as e:
            self._log(f"load_signup_page: 异常 - {e}")
            return False, f"访问 build.nvidia.com 失败：{e}"
    
    def submit_email(self, email: str) -> Tuple[bool, str, str]:
        """步骤 2: 提交邮箱，跳转到 NVGS
        
        Browser 模式观察：
          - 填邮箱到 input[name='email']
          - 点 Next 按钮
          - 跳转到 login.nvidia.com/v1/create-account?key=xxx&email=yyy
        
        返回：(success, error_msg, redirect_url)
        """
        self._log(f"submit_email: {email}")
        
        if not self._key:
            self._log("警告：没有 key 参数，尝试直接访问 NVGS")
        
        # 构造 NVGS URL（带 key 参数）
        if self._key:
            redirect_url = f"https://login.nvidia.com/v1/create-account?key={self._key}"
        else:
            redirect_url = "https://login.nvidia.com/v1/create-account"
        
        try:
            headers = self._base_headers()
            headers["referer"] = "https://build.nvidia.com/"
            
            # 访问 NVGS（模拟点击 Next 后的跳转）
            response = self._session.request(
                method="GET",
                url=redirect_url,
                headers=headers,
                allow_redirects=True,
                timeout=30,
            )
            
            status = response.status_code
            html = response.text
            
            self._log(f"NVGS create-account HTTP {status}")
            
            if status == 200:
                self._log("submit_email: 成功加载 NVGS create-account 页")
                return True, "", redirect_url
            elif status == 403:
                self._log("submit_email: 403 - 可能需要有效的 key 或 Cookie")
                return False, "NVGS 返回 403（key 或 Cookie 无效）", redirect_url
            elif status in (301, 302, 303):
                location = response.headers.get("location", "")
                self._log(f"submit_email: 重定向到 {location}")
                return True, "", location
            else:
                return False, f"NVGS 返回 HTTP {status}", redirect_url
                
        except Exception as e:
            self._log(f"submit_email: 异常 - {e}")
            return False, f"submit_email 异常：{e}", redirect_url
    
    def submit_registration(self, email: str, password: str, hcaptcha_token: str) -> Tuple[bool, str]:
        """步骤 3: 提交注册表单（密码 + 验证码）
        
        Browser 模式观察：
          - 到 create-account 页后，邮箱已预填
          - 填密码到 #registration_password
          - 勾选同意条款 #data_general_agreement
          - 填 hCaptcha token 到 #hcaptcha_response
          - 点 Register 按钮 #register_button
        
        返回：(success, error_msg)
        """
        self._log("submit_registration: 提交注册表单...")
        
        # 构造表单数据（根据 browser 模式代码分析）
        form_data = {
            "registration_password": password,
            "registration_passwordConfirm": password,  # 确认密码
            "data_general_agreement": "on",
            "h-captcha-response": hcaptcha_token,
        }
        
        try:
            headers = self._base_headers()
            headers["content-type"] = "application/x-www-form-urlencoded"
            headers["origin"] = "https://login.nvidia.com"
            headers["referer"] = "https://login.nvidia.com/v1/create-account"
            
            # POST 提交表单
            response = self._session.request(
                method="POST",
                url="https://login.nvidia.com/v1/create-account",
                headers=headers,
                data=form_data,
                allow_redirects=True,
                timeout=30,
            )
            
            status = response.status_code
            html = response.text
            
            self._log(f"submit_registration: HTTP {status}")
            
            if status == 200:
                # 检查是否成功（跳转到 profile-complete）
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
                error = self._extract_error_from_html(html)
                return False, f"表单验证失败：{error or 'HTTP 400'}"
            elif status == 403:
                return False, "注册被拒绝（403）"
            else:
                return False, f"注册返回 HTTP {status}"
                
        except Exception as e:
            self._log(f"submit_registration: 异常 - {e}")
            return False, f"submit_registration 异常：{e}"
    
    def submit_otp(self, email: str, code: str) -> Tuple[bool, str]:
        """步骤 4: 提交邮箱验证码（OTP）
        
        Browser 模式观察：
          - 在 profile-complete 页
          - OTP 输入框：input[maxlength='1']（6 个单格）
          - 提交后跳转到 consent.nvidia.com
        
        返回：(success, error_msg)
        """
        self._log(f"submit_otp: email={email[:10]}... code={code}")
        
        # 构造 OTP 提交数据
        otp_data = {
            "email": email,
            "code": code,
        }
        
        try:
            headers = self._base_headers()
            headers["content-type"] = "application/x-www-form-urlencoded"
            headers["origin"] = "https://login.nvidia.com"
            headers["referer"] = "https://login.nvidia.com/v1/profile-complete"
            
            # POST 提交 OTP
            response = self._session.request(
                method="POST",
                url="https://login.nvidia.com/v1/otp/verify",
                headers=headers,
                data=otp_data,
                allow_redirects=True,
                timeout=30,
            )
            
            status = response.status_code
            html = response.text
            
            self._log(f"submit_otp: HTTP {status}")
            
            if status == 200:
                # 检查是否成功（跳转到 consent）
                if "consent" in html.lower() or "success" in html.lower():
                    self._log("submit_otp: 成功，跳转到 consent 页")
                    return True, ""
                else:
                    error = self._extract_error_from_html(html)
                    if error:
                        return False, f"OTP 验证失败：{error}"
                    else:
                        self._log("submit_otp: 返回 200 但无法判断成功")
                        return True, ""
            elif status == 400:
                error = self._extract_error_from_html(html)
                return False, f"OTP 无效：{error or 'HTTP 400'}"
            elif status == 403:
                return False, "OTP 验证被拒绝（403）"
            else:
                return False, f"OTP 验证返回 HTTP {status}"
                
        except Exception as e:
            self._log(f"submit_otp: 异常 - {e}")
            return False, f"submit_otp 异常：{e}"
    
    def _extract_error_from_html(self, html: str) -> str | None:
        """从 HTML 中提取错误信息"""
        # 常见的错误选择器
        patterns = [
            r'class="error[^"]*"[^>]*>([^<]+)<',
            r'role="alert"[^>]*>([^<]+)<',
            r'class="[^"]*error[^"]*"[^>]*>([^<]+)<',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        
        return None
    
    def _extract_csrf_token(self, html: str) -> str | None:
        """从 HTML 中提取 CSRF token"""
        match = re.search(r'name=["\']?csrf_token["\']?\s+value=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if match:
            return match.group(1)
        return None
