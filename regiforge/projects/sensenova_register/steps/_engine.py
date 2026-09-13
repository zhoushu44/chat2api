"""商汤 SenseNova HTTP 客户端与注册共享状态。"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import string
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests


def _random_str(length: int = 12, chars: str = string.ascii_lowercase + string.digits) -> str:
    return "".join(secrets.choice(chars) for _ in range(length))


def _generate_pkce() -> tuple[str, str]:
    code_verifier = _random_str(128, string.ascii_letters + string.digits + "-._~")
    digest = hashlib.sha256(code_verifier.encode()).digest()
    return code_verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def generate_password(length: int = 16) -> str:
    prefix = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice("!@#$%^&*"),
    ]
    suffix = [secrets.choice(string.ascii_letters + string.digits) for _ in range(length - 4)]
    return "".join(prefix + suffix)


def generate_username(prefix: str = "sn", length: int = 12) -> str:
    return f"{prefix}{_random_str(length)}"


def _decode_jwt_payload(token: str) -> dict | None:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return None


class SensenovaClient:
    AUTH_URL = "https://platform.sensenova.cn/oauth2/auth"
    TOKEN_URL = "https://platform.sensenova.cn/oauth2/token"
    API_BASE = "https://platform.sensenova.cn/lite/console/v1"
    IAM_BASE = "https://iam.sensecoreapi.cn/iam/authn/v1"
    IAM_IDP = "https://iam.sensecoreapi.cn/iam/idp/v1"

    def __init__(self, proxy: str | None = None, user_agent: str = ""):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent or (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN",
            "Origin": "https://platform.sensenova.cn",
        })
        self.proxies = {"http": proxy, "https": proxy} if proxy else None
        self.code_verifier: str | None = None
        self.code_challenge: str | None = None
        self.state: str | None = None
        self.login_challenge: str | None = None
        self.token_code = ""
        self.access_token = ""
        self.refresh_token = ""
        self.user_id = ""
        self.tenant_id = ""

    def _get(self, url: str, timeout: float = 15, **kwargs: Any):
        response = self.session.get(url, proxies=self.proxies, timeout=timeout, **kwargs)
        response.raise_for_status()
        return response.json() if response.headers.get("content-type", "").startswith("application/json") else response

    def _get_raw(self, url: str, timeout: float = 15, **kwargs: Any):
        response = self.session.get(url, proxies=self.proxies, timeout=timeout, **kwargs)
        response.raise_for_status()
        return response

    def _post(self, url: str, timeout: float = 15, **kwargs: Any):
        response = self.session.post(url, proxies=self.proxies, timeout=timeout, **kwargs)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(f"{exc}; response={response.text[:500].strip()}") from exc
        return response.json() if response.headers.get("content-type", "").startswith("application/json") else response

    def fetch_login_challenge(self) -> str:
        self.code_verifier, self.code_challenge = _generate_pkce()
        self.state = _random_str(20)
        params = {
            "response_type": "code", "client_id": "nova", "code_challenge_method": "S256",
            "code_challenge": self.code_challenge, "redirect_uri": "https://platform.sensenova.cn",
            "scope": "openid offline offline_access", "state": self.state, "lang": "zh-CN",
        }
        for _ in range(3):
            response = self._get_raw(self.AUTH_URL, params=params, allow_redirects=True)
            challenge = parse_qs(urlparse(response.url).query).get("login_challenge", [None])[0]
            if not challenge:
                match = re.search(r'login_challenge["\']?\s*[:=]\s*["\']?([a-f0-9]+)', response.text)
                challenge = match.group(1) if match else None
            if challenge:
                self.login_challenge = challenge
                return challenge
            time.sleep(1)
        raise RuntimeError(f"无法获取 login_challenge, URL: {response.url}")

    def check_challenge(self) -> bool:
        data = self._get(f"{self.IAM_BASE}/auth/checkChallenge", params={"challenge": self.login_challenge}, timeout=10)
        return bool(data.get("is_valid", False))

    def send_sms(self, phone: str, region_code: str = "86", code_key: str = "") -> dict:
        payload = {"phone": phone, "region_code": region_code}
        if code_key:
            payload["code_key"] = code_key
        data = self._post(f"{self.IAM_BASE}/auth/nova/sendSmsCode", json=payload)
        self.token_code = data.get("token_code", "")
        return data

    def verify_sms(self, code: str) -> dict:
        return self._post(f"{self.IAM_BASE}/auth/nova/smsLogin", json={
            "token_code": self.token_code, "verify_code": code, "challenge": self.login_challenge,
        })

    def register(self, username: str, password: str) -> str:
        data = self._post(f"{self.IAM_BASE}/auth/nova/register", json={
            "token_code": self.token_code, "user_name": username,
            "password": password, "challenge": self.login_challenge,
        })
        redirect = data.get("redirect") or data.get("redirect_to") or data.get("redirect_uri") or ""
        if not redirect:
            raise RuntimeError(f"注册失败: {data}")
        return redirect

    def exchange_code_for_token(self, redirect_url: str) -> dict:
        response = self._get_raw(redirect_url, allow_redirects=True)
        query = parse_qs(urlparse(response.url).query)
        if "code" in query:
            return self._exchange(query["code"][0])
        challenge = query.get("login_challenge", [None])[0]
        if challenge and query.get("login_verifier", [None]):
            data = self._post(f"{self.IAM_BASE}/auth/nova/smsLogin", json={
                "token_code": self.token_code, "challenge": challenge,
            })
            redirect = data.get("redirect") or data.get("redirect_to") or data.get("redirect_uri") or ""
            if redirect:
                return self.exchange_code_for_token(redirect)
        raise RuntimeError(f"无法获取授权码: {response.url[:200]}")

    def _exchange(self, code: str) -> dict:
        data = self._post(self.TOKEN_URL, data={
            "code": code, "redirect_uri": "https://platform.sensenova.cn",
            "code_verifier": self.code_verifier, "state": self.state,
            "client_id": "nova", "grant_type": "authorization_code",
        }, headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.access_token = data.get("access_token", "")
        self.refresh_token = data.get("refresh_token", "")
        if not self.access_token:
            raise RuntimeError(f"Token 交换失败: {data}")
        payload = _decode_jwt_payload(self.access_token)
        if payload:
            ext = payload.get("ext", {})
            self.user_id = ext.get("user_id", "")
            self.tenant_id = ext.get("tenant_id", "")
        return data

    def get_api_keys(self) -> list:
        data = self._get(
            f"{self.API_BASE}/metered/api-keys",
            params={"key_type": "API_KEY_TYPE_TOKEN_PLAN", "page_size": 10},
            headers={"Authorization": f"Bearer {self.access_token}"}, timeout=10,
        )
        return data.get("api_keys", [])

    def create_api_key(self) -> dict:
        headers = {"Authorization": f"Bearer {self.access_token}"}
        payload = {"displayname": f"apikey-{time.strftime('%Y%m%d%H%M%S')}", "key_type": "API_KEY_TYPE_TOKEN_PLAN"}
        for method in ("post", "put"):
            try:
                response = getattr(self.session, method)(
                    f"{self.API_BASE}/metered/api-keys", json=payload, headers=headers,
                    proxies=self.proxies, timeout=15,
                )
                response.raise_for_status()
                data = response.json()
                if data.get("api_key"):
                    return data
            except Exception:
                continue
        raise RuntimeError("无法创建 API Key")

    def get_user_info(self) -> dict:
        if not self.user_id:
            return {}
        try:
            return self._get(
                f"{self.IAM_IDP}/users/{self.user_id}",
                headers={"Authorization": f"Bearer {self.access_token}"}, timeout=10,
            )
        except Exception:
            return {}


@dataclass
class RegistrationState:
    client: SensenovaClient
    phone: str = ""
    code: str = ""
    username: str = ""
    password: str = ""
    redirect_url: str = ""
    api_key: str = ""
    api_key_name: str = ""
    user_info: dict[str, Any] = field(default_factory=dict)
