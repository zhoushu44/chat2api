from __future__ import annotations

import asyncio
import json

import requests
import urllib3

from core.base import ExportProvider
from core.models import AccountResult, ExportResult

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class Grok2ApiExportProvider(ExportProvider):
    id = "grok2api"
    name = "导入 Grok2API"

    async def export(self, accounts: list[AccountResult]) -> ExportResult:
        base_url = str(self._config.get("base_url") or "").rstrip("/")
        admin_token = str(self._config.get("admin_password") or "").strip()
        project_id = str(self._config.get("project_id") or "").strip()
        if not base_url or not admin_token:
            return ExportResult(status="invalid", detail="缺少 Grok2API 地址或管理员 JWT")
        if project_id != "grok_register":
            return ExportResult(status="invalid", detail="当前项目产出不支持导入 Grok2API Web 账号")

        rows = [str(account.apikey).strip() for account in accounts if account.apikey]
        credentials = [str(account.apikey).strip() for account in accounts if account.apikey]
        if not rows:
            return ExportResult(status="empty", detail="没有可导入的 Grok 账号")

        proxy = str(self._config.get("proxy") or "").strip() or None
        try:
            response = await asyncio.to_thread(
                self._post_multipart,
                f"{base_url}/api/admin/v1/accounts/web/import",
                admin_token,
                "grok_web.txt",
                "\n".join(rows) + "\n",
                proxy,
            )
            created = int(response.get("created") or 0)
            updated = int(response.get("updated") or 0)
            sync_failed = int(response.get("syncFailed") or 0)
            imported = created + updated
            status = "done" if imported == len(rows) and sync_failed == 0 else "partial"
            detail = f"新增 {created}，更新 {updated}，同步失败 {sync_failed}"
            return ExportResult(
                exported=len(rows),
                imported=imported,
                status=status,
                detail=detail,
                consumed_credentials=credentials if status == "done" else [],
            )
        except requests.exceptions.SSLError as exc:
            return ExportResult(
                status="failed",
                detail=f"SSL 连接失败（检查代理/Clash 是否拦截）: {exc}",
            )
        except requests.exceptions.HTTPError as exc:
            resp = exc.response
            detail = resp.text[:500] if resp is not None else str(exc)
            code = resp.status_code if resp is not None else "?"
            return ExportResult(status="rejected", detail=f"HTTP {code}: {detail}")
        except Exception as exc:
            return ExportResult(status="failed", detail=str(exc))

    @staticmethod
    def _post_multipart(
        url: str,
        admin_token: str,
        filename: str,
        content: str,
        proxy: str | None = None,
    ) -> dict:
        proxies = {"http": proxy, "https": proxy} if proxy else None
        files = {
            "files": (filename, content.encode("utf-8"), "text/plain; charset=utf-8"),
        }
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {admin_token}",
                "Accept": "text/event-stream, application/json",
            },
            files=files,
            verify=False,
            proxies=proxies,
            timeout=300,
        )
        resp.raise_for_status()
        payload = resp.text

        # Grok2API 导入接口返回 SSE 流式响应，解析 event:complete 的 data
        result = _parse_sse(payload)
        if result is not None:
            return result

        # 兜底：直接 JSON
        if payload:
            try:
                return json.loads(payload)
            except json.JSONDecodeError:
                preview = payload[:300].replace("\n", "\\n")
                raise RuntimeError(f"响应不是 SSE 也不是 JSON（HTTP {resp.status_code}）: {preview}")
        return {}


def _parse_sse(payload: str) -> dict | None:
    """解析 SSE 流式响应，提取 event:complete 的 data。

    SSE 格式：
        : connected
        event: progress
        data: {"completed":0,"total":1,"phase":"importing"}
        ...
        event: complete
        data: {"created":1,"updated":0,"skipped":0,"synced":0,"syncFailed":1}

    返回 complete 事件的 data dict；如果有 error 事件则抛异常；无 SSE 则返回 None。
    """
    if "event:" not in payload:
        return None

    current_event = ""
    for line in payload.splitlines():
        line = line.strip()
        if not line or line.startswith(":"):
            continue
        if line.startswith("event:"):
            current_event = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data_str = line[len("data:"):].strip()
            if current_event == "complete":
                return json.loads(data_str)
            if current_event == "error":
                try:
                    err = json.loads(data_str)
                    raise RuntimeError(
                        f"Grok2API 导入失败: {err.get('code', 'unknown')}: "
                        f"{err.get('message', data_str)}"
                    )
                except json.JSONDecodeError:
                    raise RuntimeError(f"Grok2API 导入失败: {data_str}")
    return None


PROVIDER = Grok2ApiExportProvider()
