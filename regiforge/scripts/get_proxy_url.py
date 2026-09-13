"""取一个健康出口，转成 curl/Go 可用的 socks5 URL（含认证）打印。

用途：给 Go 真实协议登录测试（TestRecoveryLoginReal）提供 CHAT2API_RECOVERY_PROXY。
"""
from __future__ import annotations

import json
import sys
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import quote

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

API = "http://192.6.121.16:4433/api/proxies?num=1&type=json&format=n&sid=go-{sid}&time=20"
KEY = "zs1236547"


def fetch_proxy_auth() -> dict:
    req = urllib.request.Request(API.format(sid=uuid.uuid4().hex[:10]), headers={"X-API-Key": KEY})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())["data"]["proxies"][0]


def probe_ok(host: str, port: int, user: str, pwd: str, *, timeout: int = 12) -> bool:
    import socks as sockslib  # PySocks

    try:
        s = sockslib.socksocket()
        s.set_proxy(sockslib.SOCKS5, host, port, True, user, pwd)
        s.settimeout(timeout)
        s.connect(("auth.openai.com", 443))
        s.close()
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  [预检失败] {type(exc).__name__}: {str(exc)[:80]}", file=sys.stderr)
        return False


def main() -> int:
    tries = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    for i in range(tries):
        p = fetch_proxy_auth()
        user, pwd = p.get("username", ""), p.get("password", "")
        if probe_ok(p["ip"], int(p["port"]), user, pwd):
            if user:
                url = f"socks5://{quote(user, safe='')}:{quote(pwd, safe='')}@{p['ip']}:{int(p['port'])}"
            else:
                url = f"socks5://{p['ip']}:{int(p['port'])}"
            print(url)
            return 0
    print("连续多次取到的出口均不可用", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
