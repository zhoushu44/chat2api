"""测试 allow_redirects=True 自动跟随重定向，对比手动跟随。

还测试：每个 hop 用新 session（避免连接复用导致 BoringSSL 状态混乱）。
"""
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))

from curl_cffi import requests as cc_requests

SOCKS5 = "socks5://sockstest:socks-pass%401@192.6.121.16:7890"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"

EMAIL = f"test{int(time.time())%100000}@test.example.com"
login_url = (
    "https://api.ngc.nvidia.com/login?"
    + urlencode({"email": EMAIL, "app": "api-catalog", "redirect_uri": "https://build.nvidia.com/"})
)
nav_headers = {"accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "user-agent": UA}

# ── 方案 A: allow_redirects=True ──
print("=== 方案 A: allow_redirects=True ===")
s = cc_requests.Session(impersonate="chrome145")
s.proxies = {"http": SOCKS5, "https": SOCKS5}
try:
    resp = s.get(login_url, headers=nav_headers, allow_redirects=True, timeout=30)
    final_url = str(resp.url)
    parsed = urlparse(final_url)
    params = parse_qs(parsed.query)
    key = params.get("key", [None])[0]
    print(f"  HTTP {resp.status_code}, final={final_url[:100]}")
    print(f"  key={'✅ '+key[:40]+'...' if key else '❌ 未拿到'}")
except Exception as e:
    print(f"  ERR: {str(e)[:200]}")

# ── 方案 B: 每个 hop 用新 session ──
print("\n=== 方案 B: 每个 hop 新 session ===")
login_url2 = (
    "https://api.ngc.nvidia.com/login?"
    + urlencode({"email": EMAIL, "app": "api-catalog", "redirect_uri": "https://build.nvidia.com/"})
)
current_url = login_url2
hop = 0
key2 = None
while current_url and hop < 10:
    hop += 1
    if not current_url.startswith("http"):
        current_url = f"https://api.ngc.nvidia.com{current_url}"
    parsed = urlparse(current_url)
    params = parse_qs(parsed.query)
    if "key" in params:
        key2 = params["key"][0]
        print(f"  hop {hop}: ✅ key={key2[:40]}...")
        break
    # 每次新 session（不复用连接）
    s2 = cc_requests.Session(impersonate="chrome145")
    s2.proxies = {"http": SOCKS5, "https": SOCKS5}
    # 传递已有 cookies
    try:
        resp = s2.get(current_url, headers=nav_headers, allow_redirects=False, timeout=20)
        loc = resp.headers.get("location", "")
        print(f"  hop {hop}: HTTP {resp.status_code} {current_url[:60]}... → {loc[:60]}")
        current_url = loc
    except Exception as e:
        print(f"  hop {hop}: ERR {str(e)[:150]}")
        break

# ── 方案 C: 重试机制（同一 session，失败重试 3 次）──
print("\n=== 方案 C: 同 session + 每 hop 重试 3 次 ===")
s3 = cc_requests.Session(impersonate="chrome145")
s3.proxies = {"http": SOCKS5, "https": SOCKS5}
current_url = login_url2
hop = 0
key3 = None
while current_url and hop < 10:
    hop += 1
    if not current_url.startswith("http"):
        current_url = f"https://api.ngc.nvidia.com{current_url}"
    parsed = urlparse(current_url)
    params = parse_qs(parsed.query)
    if "key" in params:
        key3 = params["key"][0]
        print(f"  hop {hop}: ✅ key={key3[:40]}...")
        break
    success = False
    for attempt in range(3):
        try:
            resp = s3.get(current_url, headers=nav_headers, allow_redirects=False, timeout=20)
            loc = resp.headers.get("location", "")
            print(f"  hop {hop} try{attempt+1}: HTTP {resp.status_code} → {loc[:60]}")
            current_url = loc
            success = True
            break
        except Exception as e:
            print(f"  hop {hop} try{attempt+1}: ERR {str(e)[:120]}")
            time.sleep(2)
    if not success:
        print(f"  hop {hop}: 3 次重试均失败")
        break
