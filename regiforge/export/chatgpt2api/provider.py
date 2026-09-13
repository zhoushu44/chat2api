"""导入到 chatgpt2api（basketikun/chatgpt2api）。

接口：POST {base_url}/api/accounts
body: {"accounts": [{"access_token": ..., "email": ..., "type": "free", "source_type": "web"}]}
header: Authorization: Bearer {admin_password}（管理员密钥）

导入后 chatgpt2api 会自动 refresh_accounts 检测真实 type/quota/status。
"""
from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from typing import Any

from core.base import ExportProvider
from core.models import AccountResult, ExportResult


class ChatGPT2ApiExportProvider(ExportProvider):
    id = "chatgpt2api"
    name = "导入 chatgpt2api"

    async def export(self, accounts: list[AccountResult]) -> ExportResult:
        base_url = str(self._config.get("base_url") or "").rstrip("/")
        admin_token = str(self._config.get("admin_password") or "").strip()
        if not base_url or not admin_token:
            return ExportResult(status="invalid", detail="缺少 chatgpt2api 地址或管理员密钥")

        entries = []
        credentials = []
        for account in accounts:
            if not account.apikey:
                continue
            # extra 由各项目 ok_result 填充（type/source_type/plan_type）
            extra = account.extra or {}
            entry = {
                "access_token": account.apikey,
                "email": account.email or None,
                "type": extra.get("type") or "free",
                "source_type": extra.get("source_type") or "web",
            }
            # 恢复凭据：password + totp_secret 让 chatgpt2api 可在 AT 失效时走
            # 「邮箱+密码+TOTP」协议登录恢复（不等邮箱 OTP）。仅非空时带上。
            password = str(extra.get("password") or "").strip()
            if password:
                entry["password"] = password
            totp_secret = str(extra.get("totp_secret") or "").strip()
            if totp_secret:
                entry["totp_secret"] = totp_secret
            entries.append(entry)
            credentials.append(account.apikey)
        if not entries:
            return ExportResult(status="empty", detail="没有可导入的账号凭据")

        # #region debug-point A:payload-shape
        try:
            _dbg_url = "http://127.0.0.1:7777/event"
            _dbg_session = "chatgpt2api-zero-quota"
            _dbg_env = ".dbg/chatgpt2api-zero-quota.env"
            if os.path.exists(_dbg_env):
                _dbg_values = dict(line.split("=", 1) for line in open(_dbg_env, encoding="utf-8") if "=" in line)
                _dbg_url = _dbg_values.get("DEBUG_SERVER_URL", _dbg_url)
                _dbg_session = _dbg_values.get("DEBUG_SESSION_ID", _dbg_session)
            _dbg_event = {"sessionId": _dbg_session, "runId": "pre-fix", "hypothesisId": "A", "location": "export/chatgpt2api/provider.py:48", "msg": "[DEBUG] export payload shape", "data": {"entries": len(entries), "has_access_token": all(bool(item.get("access_token")) for item in entries), "token_prefixes": [str(item.get("access_token", ""))[:3] for item in entries], "types": [item.get("type") for item in entries], "source_types": [item.get("source_type") for item in entries]}}
            urllib.request.urlopen(urllib.request.Request(_dbg_url, data=json.dumps(_dbg_event).encode(), headers={"Content-Type": "application/json"}), timeout=2).read()
        except Exception:
            pass
        # #endregion
        payload = json.dumps({"accounts": entries}).encode("utf-8")
        request = urllib.request.Request(
            f"{base_url}/api/accounts",
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {admin_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            raw = await asyncio.to_thread(self._request, request)
            body = json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            return ExportResult(status="rejected", detail=f"HTTP {exc.code}: {detail}")
        except Exception as exc:
            return ExportResult(status="failed", detail=str(exc))

        added = int(body.get("added") or 0)
        skipped = int(body.get("skipped") or 0)
        # chatgpt2api 导入后会自动 refresh，refreshed 字段反映刷新成功数
        refreshed = int(body.get("refreshed") or 0)
        errors = body.get("errors") or []
        handled = added + skipped
        status = "done" if handled == len(entries) and not errors else ("partial" if handled > 0 else "rejected")
        detail = f"新增 {added}，跳过 {skipped}，已刷新 {refreshed}"
        if errors:
            detail += f"，错误 {len(errors)}：{errors[0] if isinstance(errors, list) else errors}"
        return ExportResult(
            exported=len(entries),
            imported=added,
            status=status,
            detail=detail,
            # 远端已新增或跳过的账号已经进入账号池；即使 refresh 报 token invalidated，也清理本地产出，避免重复导入失效凭据。
            consumed_credentials=credentials if handled == len(entries) else [],
        )

    @staticmethod
    def _request(request: urllib.request.Request) -> str:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read().decode("utf-8")


PROVIDER = ChatGPT2ApiExportProvider()
