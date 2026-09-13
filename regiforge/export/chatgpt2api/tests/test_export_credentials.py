"""需求 A 测试：chatgpt2api 导出透传 password / totp_secret。

不联网：拦截 urlopen，只断言 payload 形状。

运行：
    python regiforge/export/chatgpt2api/tests/test_export_credentials.py
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
        return json.dumps({"added": 1, "skipped": 0, "refreshed": 1}).encode()


def _export_and_capture(accounts):
    """运行 export，捕获发出的 payload。"""
    captured = {}

    def _fake_urlopen(request, timeout=None):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _FakeResp()

    saved = pvd.urllib.request.urlopen
    pvd.urllib.request.urlopen = _fake_urlopen
    # 关掉 debug-point 的 urlopen 干扰：直接给 provider 配置
    prov = pvd.ChatGPT2ApiExportProvider()
    prov._config = {"base_url": "http://fake.local", "admin_password": "k"}
    try:
        res = asyncio.run(prov.export(accounts))
    finally:
        pvd.urllib.request.urlopen = saved
    return captured.get("payload"), res


def _acct(email, extra):
    return AccountResult(email=email, apikey="AT-" + email, status="ok", extra=extra)


def main() -> int:
    results = []

    # TA1：带 password/totp_secret → payload 含这两字段
    payload, _ = _export_and_capture([
        _acct("a@e.com", {"type": "free", "source_type": "web", "password": "Pw1!", "totp_secret": "ABC123"}),
    ])
    entries = (payload or {}).get("accounts") or []
    ok = len(entries) == 1 and entries[0].get("password") == "Pw1!" and entries[0].get("totp_secret") == "ABC123"
    print(f"[{'PASS' if ok else 'FAIL'}] TA1 带凭据导出含 password/totp_secret -> {entries}")
    results.append(ok)

    # TA2：不带 → payload 不出现这两个 key
    payload, _ = _export_and_capture([
        _acct("b@e.com", {"type": "free", "source_type": "web"}),
    ])
    entries = (payload or {}).get("accounts") or []
    ok = len(entries) == 1 and "password" not in entries[0] and "totp_secret" not in entries[0]
    print(f"[{'PASS' if ok else 'FAIL'}] TA2 无凭据导出不含这两 key -> {entries}")
    results.append(ok)

    # TA3：空字符串也不带（避免污染 payload）
    payload, _ = _export_and_capture([
        _acct("c@e.com", {"type": "free", "source_type": "web", "password": "", "totp_secret": "   "}),
    ])
    entries = (payload or {}).get("accounts") or []
    ok = len(entries) == 1 and "password" not in entries[0] and "totp_secret" not in entries[0]
    print(f"[{'PASS' if ok else 'FAIL'}] TA3 空白凭据不带 -> {entries}")
    results.append(ok)

    # TA4（回归）：原 4 字段不变
    payload, _ = _export_and_capture([
        _acct("d@e.com", {"type": "free", "source_type": "web"}),
    ])
    e = ((payload or {}).get("accounts") or [{}])[0]
    ok = e.get("access_token") == "AT-d@e.com" and e.get("email") == "d@e.com" and e.get("type") == "free" and e.get("source_type") == "web"
    print(f"[{'PASS' if ok else 'FAIL'}] TA4 原 4 字段回归 -> {e}")
    results.append(ok)

    print("-" * 50)
    print(f"结果：{sum(results)}/{len(results)} 通过")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
