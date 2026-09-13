"""step06：登录主界面后从 localStorage 提取 token 作为 accessToken 凭证。

返回 dict：{"token": ..., "user_id": ...}。user_id 从 JWT payload 解码，供表格展示与导出。
"""
from __future__ import annotations

import base64
import json

from typing import Any


def decode_user_id(token: str) -> str:
    """从 ES256 JWT 的 payload 解码 user_id（如 {"id": "..."}）。"""
    try:
        payload = token.split(".")[1]
        pad = "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload + pad))
        for key in ("id", "user_id", "sub"):
            if data.get(key):
                return str(data[key])
    except Exception:
        pass
    return ""


async def run(page: Any) -> dict:
    token = await page.evaluate(
        """() => {
            try { return localStorage.getItem('token') || ''; } catch (e) { return ''; }
        }"""
    )
    if not token:
        return {"token": "", "user_id": ""}
    try:
        parsed = json.loads(token)
        if isinstance(parsed, dict):
            token = parsed.get("accessToken") or parsed.get("token") or token
    except Exception:
        pass
    return {"token": token, "user_id": decode_user_id(token)}
