from __future__ import annotations

from pathlib import Path

from core.base import ExportProvider
from core.models import AccountResult, ExportResult
from core.paths import ROOT


class FileExportProvider(ExportProvider):
    id = "file"
    name = "导出到文件夹"

    async def export(self, accounts: list[AccountResult]) -> ExportResult:
        folder = Path(str(self._config.get("output_dir") or "data/exports")).expanduser()
        if not folder.is_absolute():
            folder = ROOT / folder
        folder.mkdir(parents=True, exist_ok=True)
        filename = str(self._config.get("filename") or "accounts.txt").strip()
        target = folder / filename
        rows = [f"{account.email}|{account.apikey}" for account in accounts if account.apikey]
        target.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")
        return ExportResult(
            exported=len(rows),
            status="done",
            detail=str(target),
            imported=len(rows),
        )


PROVIDER = FileExportProvider()
