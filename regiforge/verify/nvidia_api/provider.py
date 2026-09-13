from __future__ import annotations

import asyncio
import urllib.error
import urllib.request

from core.base import VerificationProvider
from core.models import AccountResult, VerificationResult


class NvidiaApiVerificationProvider(VerificationProvider):
    id = "nvidia_api"
    name = "NVIDIA API 连通性验证"

    async def verify(self, account: AccountResult) -> VerificationResult:
        api_key = (account.apikey or "").strip()
        if not api_key:
            return VerificationResult(account_id=account.email, status="invalid", detail="缺少 NVIDIA API Key")

        url = str(self._config.get("api_url") or "https://integrate.api.nvidia.com/v1/models").strip()
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
        try:
            response = await asyncio.to_thread(urllib.request.urlopen, request, timeout=20)
            with response:
                return VerificationResult(account_id=account.email, usable=True, status="usable", detail=f"HTTP {response.status}")
        except urllib.error.HTTPError as exc:
            return VerificationResult(account_id=account.email, status="rejected", detail=f"HTTP {exc.code}")
        except Exception as exc:
            return VerificationResult(account_id=account.email, status="unreachable", detail=str(exc))


PROVIDER = NvidiaApiVerificationProvider()
