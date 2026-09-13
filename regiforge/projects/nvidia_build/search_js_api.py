"""下载 NVGS 主 JS 文件，搜索创建账户 API 端点"""
import re
from curl_cffi import requests as cc_requests

proxy = "http://127.0.0.1:7897"
session = cc_requests.Session(impersonate="chrome145")
session.proxies = {"http": proxy, "https": proxy}

# 下载 main JS
js_url = "https://login.nvgs.nvidia.com/main-Y376OYFP.js"
print(f"下载: {js_url}")
resp = session.get(js_url, timeout=60)
print(f"HTTP {resp.status_code}, {len(resp.text)} bytes")

if resp.status_code == 200:
    js = resp.text

    # 搜索所有 API 路径
    print("\n=== /api/ 路径 ===")
    apis = set(re.findall(r'["\'](/api/[0-9a-zA-Z/_-]+)["\']', js))
    for a in sorted(apis):
        print(f"  {a}")

    # 搜索 oauth 路径
    print("\n=== oauth 路径 ===")
    oauth = set(re.findall(r'["\'](/api/1/frontend/oauth/[0-9a-zA-Z/_-]+)["\']', js))
    for o in sorted(oauth):
        print(f"  {o}")

    # 搜索 create/register
    print("\n=== create/register 相关 ===")
    creates = re.findall(r'["\']([^"\']*(?:create|register|signup)[^"\']*)["\']', js, re.IGNORECASE)
    for c in sorted(set(creates)):
        if 10 < len(c) < 100 and ('api' in c.lower() or 'oauth' in c.lower() or '/v' in c.lower()):
            print(f"  {c}")

    # 搜索 account 相关
    print("\n=== account 相关 ===")
    accounts = re.findall(r'["\']([^"\']*account[^"\']*)["\']', js, re.IGNORECASE)
    for a in sorted(set(accounts)):
        if 10 < len(a) < 100 and ('api' in a.lower() or 'oauth' in a.lower() or '/' in a):
            print(f"  {a}")
