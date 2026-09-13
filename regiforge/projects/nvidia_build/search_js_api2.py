"""搜索 NVGS JS 文件中的 API 端点（更全面的搜索）"""
import re
from curl_cffi import requests as cc_requests

proxy = "http://127.0.0.1:7897"
session = cc_requests.Session(impersonate="chrome145")
session.proxies = {"http": proxy, "https": proxy}

# 下载多个 JS 文件
js_files = [
    "https://login.nvgs.nvidia.com/main-Y376OYFP.js",
    "https://login.nvgs.nvidia.com/scripts-VJRURFI4.js",
]

for js_url in js_files:
    print(f"\n{'='*60}")
    print(f"下载: {js_url}")
    resp = session.get(js_url, timeout=60)
    print(f"HTTP {resp.status_code}, {len(resp.text)} bytes")

    if resp.status_code != 200:
        continue

    js = resp.text

    # 搜索所有包含 account/create/register/signup 的字符串
    print(f"\n--- 包含 account/create/register/signup 的字符串 ---")
    patterns = re.findall(r'["\'`]([^"\'`\n]{5,100})["\'`]', js)
    keywords = ['account/create', 'account/register', 'account/signup', 'create-account',
                'register', 'signup', 'account/submit', '/account', 'oauth/account',
                'createAccount', 'registerAccount']
    found = set()
    for p in patterns:
        for kw in keywords:
            if kw.lower() in p.lower():
                found.add(p)
    for f in sorted(found):
        print(f"  {f}")

    # 搜索 fetch/post 调用
    print(f"\n--- http.post/fetch 调用 ---")
    posts = re.findall(r'(?:post|fetch)\s*\(\s*["\'`]([^"\'`]+)', js, re.IGNORECASE)
    for p in sorted(set(posts)):
        if len(p) > 3:
            print(f"  {p}")

    # 搜索 backtick 模板字符串中的 API 路径
    print(f"\n--- 模板字符串中的路径 ---")
    templates = re.findall(r'`([^`]*account[^`]*)`', js, re.IGNORECASE)
    for t in sorted(set(templates)):
        if len(t) < 100:
            print(f"  {t}")
