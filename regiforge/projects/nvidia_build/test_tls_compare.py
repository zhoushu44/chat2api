"""对比测试：HTTP forwarder vs SOCKS5 直连，定位 api.ngc.nvidia.com 的 TLS 错误根因。

阶段 2 连 accounts.nvgs.nvidia.com 成功，阶段 1 连 api.ngc.nvidia.com 失败。
本脚本对比 4 种组合，确认是代理类型问题还是域名特定问题。
"""
import sys
from pathlib import Path

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))

from curl_cffi import requests as cc_requests

HTTP_FWD = "http://127.0.0.1:5777"
SOCKS5 = "socks5://sockstest:socks-pass%401@192.6.121.16:7890"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"

TARGETS = [
    ("api.ngc.nvidia.com", "https://api.ngc.nvidia.com/login?app=api-catalog&redirect_uri=https://build.nvidia.com/"),
    ("accounts.nvgs.nvidia.com", "https://accounts.nvgs.nvidia.com/api/1/health"),
]

PROXIES = [
    ("HTTP-fwd", HTTP_FWD),
    ("SOCKS5", SOCKS5),
]


def test_combo(proxy_name, proxy_url, domain, url):
    s = cc_requests.Session(impersonate="chrome145")
    s.proxies = {"http": proxy_url, "https": proxy_url}
    try:
        r = s.get(url, headers={"user-agent": UA, "accept": "text/html,*/*"}, allow_redirects=False, timeout=20)
        return f"HTTP {r.status_code}, len={len(r.text)}"
    except Exception as e:
        return f"ERR: {str(e)[:150]}"


print(f"{'proxy':<10} {'domain':<28} {'result'}")
print("-" * 100)
for pname, purl in PROXIES:
    for domain, url in TARGETS:
        res = test_combo(pname, purl, domain, url)
        print(f"{pname:<10} {domain:<28} {res}")
        sys.stdout.flush()
