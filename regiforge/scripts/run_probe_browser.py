"""跑 probe_login_browser（自动提取代理，避免会话过期）。"""
from __future__ import annotations

import argparse
import subprocess
import sys
import uuid
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import json  # noqa: E402
import urllib.request  # noqa: E402

API = "http://192.6.121.16:4433/api/proxies?num=1&type=json&format=n&sid=probe-{sid}&time=20"
KEY = "zs1236547"


def fetch_proxy_auth() -> dict:
    """取带认证的 SOCKS5（whitelist_mode=true 时白名单端口不可靠，认证端口才稳）。"""
    req = urllib.request.Request(API.format(sid=uuid.uuid4().hex[:10]), headers={"X-API-Key": KEY})
    with urllib.request.urlopen(req, timeout=20) as resp:
        p = json.loads(resp.read().decode())["data"]["proxies"][0]
    return p


def probe_ok(host: str, port: int, user: str, pwd: str, *, timeout: int = 12) -> bool:
    """用 socks5 直连 auth.openai.com:443 预检出口是否可用（避免把坏出口带进浏览器）。"""
    import socket
    try:
        import socks as sockslib  # PySocks
        s = sockslib.socksocket()
        s.set_proxy(sockslib.SOCKS5, host, port, True, user, pwd)
        s.settimeout(timeout)
        s.connect(("auth.openai.com", 443))
        s.close()
        return True
    except Exception as exc:
        print(f"    [预检失败] {type(exc).__name__}: {str(exc)[:80]}", flush=True)
        return False


def pick_healthy_proxy(*, tries: int = 6) -> dict:
    """多取几次，选第一个能连通的出口。"""
    for i in range(tries):
        p = fetch_proxy_auth()
        print(f"  [尝试{i+1}] exit={p.get('exit_ip')} port={p.get('port')}", flush=True)
        if probe_ok(p["ip"], int(p["port"]), p.get("username", ""), p.get("password", "")):
            print(f"  [选中] exit={p.get('exit_ip')}", flush=True)
            return p
    raise RuntimeError("连续多次取到的出口均不可用")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", default="pwpage")
    ap.add_argument("--email", default="zlef4d581b03muidxq@outlook.com")
    ap.add_argument("--password", default="vVdb9vjBPd!A1")
    ap.add_argument("--totp", default="3VCJZ7LBXRFUCJCS4RF3RHE7P24V47L2")
    args = ap.parse_args()

    p = pick_healthy_proxy()
    print(f"[PROXY-RAW] {json.dumps(p, ensure_ascii=False)}", flush=True)

    # 起本地 HTTP 转发器：Chrome 只认 http://127.0.0.1:port，转发器带凭据连远端 SOCKS5
    from proxy.socks5.http_forwarder import Socks5HttpForwarder  # noqa: E402

    fwd = Socks5HttpForwarder(
        remote_host=p["ip"],
        remote_port=int(p["port"]),
        username=p.get("username", ""),
        password=p.get("password", ""),
    )
    local = fwd.start_sync()
    print(f"[FORWARDER] {local} -> socks5://{p['ip']}:{p['port']} (auth)\n", flush=True)
    try:
        return subprocess.call([
            sys.executable, str(_ROOT / "scripts" / "probe_login_browser.py"),
            "--email", args.email, "--password", args.password, "--totp", args.totp,
            "--proxy", local, "--step", args.step,
        ])
    finally:
        fwd.running = False


if __name__ == "__main__":
    raise SystemExit(main())
