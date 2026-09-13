from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from typing import Any

from core.base import ExportProvider
from core.models import AccountResult, ExportResult


class Sub2ApiExportProvider(ExportProvider):
    id = "sub2api"
    name = "导入 Sub2API"

    # 内置默认账号模板（UI 不再显示该字段时使用）
    DEFAULT_TEMPLATE = {
        "name": "$email",
        "platform": "openai",
        "type": "oauth",
        "credentials": {"access_token": "$credential"},
    }

    async def export(self, accounts: list[AccountResult]) -> ExportResult:
        base_url = str(self._config.get("base_url") or "").rstrip("/")
        access_token = str(self._config.get("admin_access_token") or "").strip()
        if not base_url or not access_token:
            return ExportResult(status="invalid", detail="缺少 Sub2API 地址或管理员访问令牌")

        template = self.DEFAULT_TEMPLATE
        entries = []
        for index, account in enumerate(accounts, start=1):
            if not account.apikey:
                continue
            entry = self._replace(template, account, index)
            entry.setdefault("name", account.email or f"account-{index}")
            entries.append(entry)
        if not entries:
            return ExportResult(status="empty", detail="没有可导入的账号凭据")

        payload = json.dumps({"accounts": entries}).encode("utf-8")
        request = urllib.request.Request(
            f"{base_url}/api/v1/admin/accounts/batch",
            data=payload,
            method="POST",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        )
        try:
            raw = await asyncio.to_thread(self._request, request)
            body = json.loads(raw)
        except urllib.error.HTTPError as exc:
            return ExportResult(status="rejected", detail=f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')}")
        except Exception as exc:
            return ExportResult(status="failed", detail=str(exc))

        success = int(body.get("success") or 0)
        failed = int(body.get("failed") or 0)
        detail = f"成功 {success}，失败 {failed}"
        return ExportResult(
            exported=success,
            status="done" if failed == 0 else "partial",
            detail=detail,
            imported=success,
            consumed_credentials=[account.apikey for account in accounts if account.apikey] if failed == 0 else [],
        )

    @staticmethod
    def _request(request: urllib.request.Request) -> str:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read().decode("utf-8")

    @classmethod
    def _replace(cls, value: Any, account: AccountResult, index: int) -> Any:
        tokens = {"$email": account.email, "$credential": account.apikey or "", "$index": index}
        if isinstance(value, dict):
            return {key: cls._replace(item, account, index) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._replace(item, account, index) for item in value]
        if isinstance(value, str):
            for key, replacement in tokens.items():
                value = value.replace(key, str(replacement))
        return value


PROVIDER = Sub2ApiExportProvider()
