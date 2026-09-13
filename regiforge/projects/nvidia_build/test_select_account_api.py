"""分析 select-account SPA 页面，找出 org 创建 API 端点。

Next.js 页面通常在 __NEXT_DATA__ 中包含 API 路由信息。
还搜索 JS bundle 中的 fetch/axios 调用路径。
"""
import sys
import re
import json
from pathlib import Path

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))

from curl_cffi import requests as cc_requests

SOCKS5 = "socks5://sockstest:socks-pass%401@192.6.121.16:7890"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"

s = cc_requests.Session(impersonate="chrome145")
s.proxies = {"http": SOCKS5, "https": SOCKS5}

url = "https://cloudaccounts.nvidia.com/sf/v2/select-account?redirect_uri=https://login.nvidia.com/"
print(f"GET {url[:80]}...")

for attempt in range(3):
    try:
        resp = s.get(url, headers={"user-agent": UA, "accept": "text/html,*/*"}, timeout=30)
        break
    except Exception as e:
        print(f"  try{attempt+1} ERR: {str(e)[:120]}")
        if attempt < 2:
            import time; time.sleep(2)
else:
    print("3 次重试失败")
    sys.exit(1)

html = resp.text or ""
print(f"HTTP {resp.status_code}, len={len(html)}")

# 1. 提取 __NEXT_DATA__
nd = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
if nd:
    try:
        data = json.loads(nd.group(1))
        print(f"\n=== __NEXT_DATA__ keys: {sorted(data.keys())} ===")
        if "props" in data:
            props = data["props"]
            if isinstance(props, dict):
                print(f"  props keys: {sorted(props.keys())}")
                page_props = props.get("pageProps", {})
                if isinstance(page_props, dict):
                    print(f"  pageProps keys: {sorted(page_props.keys())}")
                    for k, v in page_props.items():
                        print(f"    {k}: {json.dumps(v, ensure_ascii=False)[:200]}")
        if "runtimeConfig" in data:
            rc = data["runtimeConfig"]
            print(f"\n  runtimeConfig: {json.dumps(rc, ensure_ascii=False)[:500]}")
    except Exception as e:
        print(f"  __NEXT_DATA__ parse err: {e}")
        print(f"  raw: {nd.group(1)[:500]}")
else:
    print("\n(no __NEXT_DATA__)")

# 2. 搜索 API 端点线索
print("\n=== API 端点线索 ===")
api_patterns = [
    r'["\']/(api|sf|v[0-9])/[^"\']+["\']',
    r'["\']https?://[^"\']*(api\.ngc|cloudaccounts)[^"\']*["\']',
    r'fetch\(["\']([^"\']+)',
    r'["\']/orgs?["\']',
    r'["\'].*org.*["\']',
]
for pat in api_patterns:
    matches = re.findall(pat, html, re.I)
    if matches:
        unique = sorted(set(matches))[:10]
        print(f"  pattern {pat[:40]}: {unique}")

# 3. 搜索 JS bundle URLs
js_urls = re.findall(r'src="(/_next/static/chunks/[^"]+)"', html)
print(f"\n=== JS bundles: {len(js_urls)} ===")
for u in js_urls[:5]:
    print(f"  {u}")

# 4. 提取第一个 JS bundle，搜索 API 路径
if js_urls:
    js_url = f"https://cloudaccounts.nvidia.com{js_urls[0]}"
    print(f"\n=== Fetching first JS bundle: {js_url[:80]}... ===")
    try:
        js_resp = s.get(js_url, headers={"user-agent": UA}, timeout=30)
        js_text = js_resp.text or ""
        print(f"  JS len={len(js_text)}")
        # 搜索 API 路径
        api_refs = re.findall(r'["\']/(api|sf|v[0-9])/[^"\']{3,40}["\']', js_text)
        if api_refs:
            print(f"  API refs in JS: {sorted(set(api_refs))[:15]}")
        org_refs = re.findall(r'["\'][^"\']*org[^"\']*["\']', js_text, re.I)
        if org_refs:
            print(f"  org refs in JS: {sorted(set(org_refs))[:15]}")
        fetch_refs = re.findall(r'fetch\(["\']([^"\']+)["\']', js_text)
        if fetch_refs:
            print(f"  fetch refs: {sorted(set(fetch_refs))[:10]}")
    except Exception as e:
        print(f"  JS fetch err: {e}")
