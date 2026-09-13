"""测试纯 HTTP 阶段 1 完整重定向链，确认哪个 hop 被代理关闭。

重定向链：
  api.ngc.nvidia.com/login → 302 → login.nvidia.com/authorize →
  302 → accounts.nvgs.nvidia.com/api/1/oauth/authorize →
  302 → login.nvgs.nvidia.com/v1/login?key=xxx
"""
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))

from curl_cffi import requests as cc_requests

SOCKS5 = "socks5://sockstest:socks-pass%401@192.6.121.16:7890"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"

EMAIL = f"test{int(__import__('time').time())%100000}@test.example.com"
login_url = (
    "https://api.ngc.nvidia.com/login?"
    + urlencode({"email": EMAIL, "app": "api-catalog", "redirect_uri": "https://build.nvidia.com/"})
)

nav_headers = {"accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "user-agent": UA}

session = cc_requests.Session(impersonate="chrome145")
session.proxies = {"http": SOCKS5, "https": SOCKS5}

print(f"初始 GET: {login_url[:80]}...")
try:
    resp = session.get(login_url, headers=nav_headers, allow_redirects=False, timeout=20)
    print(f"  → HTTP {resp.status_code}, location={resp.headers.get('location', '')[:100]}")
except Exception as e:
    print(f"  → ERR: {e}")
    sys.exit(1)

current_url = resp.headers.get("location", "")
hop = 0
while current_url and hop < 10:
    hop += 1
    if not current_url.startswith("http"):
        current_url = f"https://api.ngc.nvidia.com{current_url}"
    parsed = urlparse(current_url)
    params = parse_qs(parsed.query)
    if "key" in params:
        print(f"  hop {hop}: ✅ 拿到 key={params['key'][0][:40]}... (URL={current_url[:80]})")
        break
    print(f"  hop {hop}: GET {current_url[:90]}...")
    try:
        resp = session.get(current_url, headers=nav_headers, allow_redirects=False, timeout=20)
        loc = resp.headers.get("location", "")
        print(f"    → HTTP {resp.status_code}, location={loc[:100]}")
        current_url = loc
    except Exception as e:
        print(f"    → ERR: {str(e)[:180]}")
        break

print(f"\n最终 hop={hop}, cookies={len(list(session.cookies.jar)) if hasattr(session.cookies, 'jar') else 'n/a'}")
