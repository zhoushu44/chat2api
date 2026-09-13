import urllib.request, json, sys

body = json.dumps({
    "project_id": "nvidia_build",
    "captcha_id": "hcaptcha.captcharun",
    "email_id": "tempmail",
    "proxy_id": "socks5",
    "total": 5,
    "start": 1,
    "concurrency": 2,
    "stagger": 0,
    "headless": False,
}).encode()

req = urllib.request.Request(
    "http://127.0.0.1:8000/api/tasks",
    data=body,
    headers={"Content-Type": "application/json"},
)
try:
    resp = urllib.request.urlopen(req, timeout=10)
    d = json.loads(resp.read())
    print("task_id:", d.get("task_id"))
    print("state:", d.get("state"))
    print("total:", d.get("total"))
except urllib.error.HTTPError as e:
    print("HTTP error:", e.code, e.read().decode()[:500])
except Exception as e:
    print("error:", type(e).__name__, e)
sys.stdout.flush()
