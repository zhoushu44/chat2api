"""检查 login.nvidia.com/authorize 重定向链中的 state 参数。"""
import os
from urllib.parse import urlencode, urlparse, parse_qs
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
from curl_cffi import requests as cc_requests

PROXY = os.getenv("IPDEEP_DYNAMIC_LINK", "").replace("socks5h://", "socks5://")
print("proxy:", bool(PROXY))
s = cc_requests.Session(impersonate="chrome145")
if PROXY:
    s.proxies = {"http": PROXY, "https": PROXY}
H = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
    "referer": "https://build.nvidia.com/",
}
login_url = (
    "https://api.ngc.nvidia.com/login?"
    + urlencode({"email": "test_probe@example.com", "app": "api-catalog", "redirect_uri": "https://build.nvidia.com/"})
)
r = s.get(login_url, headers=H, allow_redirects=False, timeout=30)
print("hop0 Location:", (r.headers.get("location", "") or "(none)")[:250])
cu = r.headers.get("location", "")
for i in range(6):
    if not cu:
        break
    p = urlparse(cu)
    q = parse_qs(p.query)
    print(f"hop{i+1} host={p.hostname} path={p.path} query_keys={sorted(q.keys())}")
    if "state" in q:
        print(f"  STATE={q['state'][0][:80]}")
    if "key" in q:
        print(f"  KEY={q['key'][0][:40]}...")
        break
    r = s.get(cu, headers=H, allow_redirects=False, timeout=30)
    loc = r.headers.get("location", "")
    print(f"  HTTP {r.status_code} loc={(loc or '(none)')[:180]}")
    if r.status_code not in (301, 302, 303, 307, 308) or not loc:
        print(f"  [stop] body_len={len(r.text or '')}")
        break
    cu = loc
print("done")
