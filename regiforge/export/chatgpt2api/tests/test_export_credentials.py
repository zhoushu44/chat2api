"""chatgpt2api 导出透传恢复凭据：password / totp_secret / session_token。

不联网：拦截 urlopen，只断言单账号 POST 的 payload 形状与成功判定。
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

_REGIROOT = Path(__file__).resolve().parents[3]
if str(_REGIROOT) not in sys.path:
    sys.path.insert(0, str(_REGIROOT))

from core.models import AccountResult  # noqa: E402
from export.chatgpt2api import provider as pvd  # noqa: E402


class _FakeResp:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps({"token": "AT-new", "email": "a@e.com"}).encode()


def _export_and_capture(accounts):
    captured = {}

    def _fake_urlopen(request, timeout=None):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["url"] = request.full_url
        return _FakeResp()

    saved = pvd.urllib.request.urlopen
    pvd.urllib.request.urlopen = _fake_urlopen
    prov = pvd.ChatGPT2ApiExportProvider()
    prov._config = {"base_url": "http://fake.local", "admin_password": "k"}
    try:
        res = asyncio.run(prov.export(accounts))
    finally:
        pvd.urllib.request.urlopen = saved
    return captured, res


def _acct(email, extra):
    return AccountResult(email=email, apikey="AT-" + email, status="ok", extra=extra)


def main() -> int:
    results = []

    # TA1：带恢复凭据 → 单账号 payload 含 password/totp_secret/session_token
    captured, result = _export_and_capture([
        _acct("a@e.com", {
            "type": "free", "source_type": "web",
            "password": " Pw1! ", "totp_secret": " ABC123 ", "session_token": " ST-1 ",
        }),
    ])
    entry = captured.get("payload") or {}
    ok = (
        entry.get("password") == "Pw1!"
        and entry.get("totp_secret") == "ABC123"
        and entry.get("session_token") == "ST-1"
        and captured.get("url") == "http://fake.local/api/accounts"
        and result.imported == 1
    )
    print(f"[{'PASS' if ok else 'FAIL'}] TA1 恢复凭据透传 + 单账号导入成功")
    results.append(ok)

    # TA2：不带 → payload 不出现恢复凭据 key
    captured, _ = _export_and_capture([_acct("b@e.com", {"type": "free", "source_type": "web"})])
    entry = captured.get("payload") or {}
    ok = all(k not in entry for k in ("password", "totp_secret", "session_token"))
    print(f"[{'PASS' if ok else 'FAIL'}] TA2 无凭据不带恢复字段")
    results.append(ok)

    # TA3：空白凭据不发送，原有字段保持不变
    captured, _ = _export_and_capture([
        _acct("c@e.com", {"type": "free", "source_type": "web", "password": "", "totp_secret": "   "}),
    ])
    entry = captured.get("payload") or {}
    ok = (
        all(k not in entry for k in ("password", "totp_secret", "session_token"))
        and entry.get("token") == "AT-c@e.com"
        and entry.get("email") == "c@e.com"
        and entry.get("type") == "free"
        and entry.get("source_type") == "web"
        and entry.get("status") == "正常"
    )
    print(f"[{'PASS' if ok else 'FAIL'}] TA3 空白凭据不带 + 原字段回归")
    results.append(ok)

    print("-" * 50)
    print(f"结果：{sum(results)}/{len(results)} 通过")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
