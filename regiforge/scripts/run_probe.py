"""D 段探索：自动提取代理后跑 probe_login，避免会话过期。

用法：
    python regiforge/scripts/run_probe.py --step login
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import uuid
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import urllib.request  # noqa: E402
import json  # noqa: E402

API = "http://192.6.121.16:4433/api/proxies?num=1&type=json&format=n&sid=probe-{sid}&time=20"
KEY = "zs1236547"


def fetch_proxy() -> str:
    sid = uuid.uuid4().hex[:10]
    req = urllib.request.Request(API.format(sid=sid), headers={"X-API-Key": KEY})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode())
    p = data["data"]["proxies"][0]
    # 优先白名单端口（curl 不支持带认证的 socks5）
    wl = p.get("proxy_whitelist") or ""
    if wl:
        return wl.replace("socks5://", "socks5h://")
    return p["proxy"].replace("socks5://", "socks5h://")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", default="login")
    ap.add_argument("--email", default="zlef4d581b03muidxq@outlook.com")
    ap.add_argument("--password", default="vVdb9vjBPd!A1")
    ap.add_argument("--totp", default="3VCJZ7LBXRFUCJCS4RF3RHE7P24V47L2")
    args = ap.parse_args()

    proxy = fetch_proxy()
    print(f"[PROXY] {proxy}\n")
    cmd = [
        sys.executable,
        str(_ROOT / "scripts" / "probe_login.py"),
        "--email", args.email,
        "--password", args.password,
        "--totp", args.totp,
        "--step", args.step,
        "--proxy", proxy,
    ]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
