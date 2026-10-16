"""导入到 chatgpt2api（Go 重写版，单账号接口）。

接口：POST {base_url}/api/accounts
body: {"id": <email>, "token": <access_token>, "email": ..., "type": "free",
       "source_type": "web", "status": "正常", "quota": -1, "quota_unknown": true}
header: Authorization: Bearer {admin_password}（管理员密钥）

注意：Go 重写版的 /api/accounts 只接受单个账号对象（不接受批量数组），
token 字段名是 token（旧 Python 版为 access_token），故逐个提交。
新号 quota 未知：quota=-1 + quota_unknown=true 使调度器视为可用。
"""
from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request

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
            email = account.email or ""
            extra = account.extra or {}
            entry = {
                "id": email or None,
                "token": account.apikey,
                "email": email or None,
                "type": extra.get("type") or "free",
                "source_type": extra.get("source_type") or "web",
                "status": "正常",
                "quota": -1,
                "quota_unknown": True,
            }
            entries.append(entry)
            credentials.append(account.apikey)
        if not entries:
            return ExportResult(status="empty", detail="没有可导入的账号凭据")

        added = 0
        errors: list[str] = []
        for entry in entries:
            payload = json.dumps(entry).encode("utf-8")
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
            label = entry.get("email") or "unknown"
            try:
                raw = await asyncio.to_thread(self._request, request)
                body = json.loads(raw) if raw else {}
                if body.get("token"):
                    added += 1
                else:
                    errors.append(f"{label}: 响应缺少 token")
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")
                errors.append(f"{label}: HTTP {exc.code}: {detail[:200]}")
            except Exception as exc:
                errors.append(f"{label}: {exc}")

        status = "done" if not errors else ("partial" if added > 0 else "rejected")
        detail = f"新增 {added}/{len(entries)}"
        if errors:
            detail += f"，错误 {len(errors)}：{errors[0]}"
        return ExportResult(
            exported=len(entries),
            imported=added,
            status=status,
            detail=detail,
            # 全部导入成功才清理本地产出，避免重复导入失效凭据
            consumed_credentials=credentials if added == len(entries) else [],
        )

    @staticmethod
    def _request(request: urllib.request.Request) -> str:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read().decode("utf-8")


PROVIDER = ChatGPT2ApiExportProvider()
