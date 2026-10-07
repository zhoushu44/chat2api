#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Login probe: replicate oauth.LoginWithPassword but with REAL sentinel + curl_cffi fingerprint.
Usage: python3 _login_probe.py <email> <password> [proxy|-] [flow_pw]
"""
import sys, os, json, uuid, importlib.util, traceback

try:
    from curl_cffi import requests as creq
except Exception as e:
    print("import curl_cffi failed:", e); sys.exit(2)

EMAIL = sys.argv[1]
PASSWORD = sys.argv[2]
PROXY = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] not in ("", "-", "none") else None
FLOW_PW = sys.argv[4] if len(sys.argv) > 4 else os.environ.get("FLOW_PW", "authorize_continue")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
IMP = "chrome131"
CHAT = "https://chatgpt.com"
AUTH = "https://auth.openai.com"

def load_sq():
    p = "/app/projects/chatgpt_register/steps/_sentinel_quickjs.py"
    spec = importlib.util.spec_from_file_location("_sq_probe", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

sq = load_sq()
did = str(uuid.uuid4())
print("== target=%s proxy=%s flow_pw=%s did=%s" % (EMAIL, PROXY or "DIRECT", FLOW_PW, did))

s = creq.Session()
base = {"impersonate": IMP, "timeout": 40}
if PROXY:
    base["proxy"] = PROXY

def sent(flow):
    try:
        res = sq.get_sentinel_token_via_quickjs(s, did, flow=flow, log=lambda m: print("   [sq]", m),
                                                user_agent=UA, proxy=PROXY, impersonate=IMP)
    except Exception as e:
        print("   sentinel EXC:", repr(e)[:200]); return ("", "")
    if not res:
        return ("", "")
    return res

try:
    # 1) csrf
    r = s.get(CHAT + "/api/auth/csrf", **base)
    print("[1] csrf", r.status_code, r.text[:120].replace("\n", " "))
    csrf = (r.json() or {}).get("csrfToken", "")

    # 2) signin
    r = s.post(CHAT + "/api/auth/signin/openai",
               data={"csrfToken": csrf, "callbackUrl": "/"},
               headers={"Content-Type": "application/x-www-form-urlencoded"},
               allow_redirects=False, **base)
    loc = r.headers.get("Location", "")
    print("[2] signin", r.status_code, "loc=" + loc[:110])

    # 3) authorize follow
    cur = loc
    for i in range(8):
        r = s.get(cur, allow_redirects=False, **base)
        if 300 <= r.status_code < 400:
            cur = r.headers.get("Location", ""); continue
        break
    print("[3] authorize", r.status_code, "cur=" + cur[:110])

    # 4) continue (email)
    tok, so = sent("authorize_continue")
    print("[4] sentinel continue len=%d so=%s" % (len(tok), bool(so)))
    h = {"Content-Type": "application/json", "Origin": AUTH, "Referer": AUTH + "/log-in"}
    if tok: h["openai-sentinel-token"] = tok
    if so: h["openai-sentinel-so-token"] = so
    r = s.post(AUTH + "/api/accounts/authorize/continue",
               json={"username": {"kind": "email", "value": EMAIL}},
               headers=h, allow_redirects=False, **base)
    print("[4] continue", r.status_code, r.text[:400].replace("\n", " "))

    # 5) password verify
    tok2, so2 = sent(FLOW_PW)
    print("[5] sentinel password len=%d so=%s" % (len(tok2), bool(so2)))
    h2 = {"Content-Type": "application/json", "Origin": AUTH, "Referer": AUTH + "/log-in/password"}
    if tok2: h2["openai-sentinel-token"] = tok2
    if so2: h2["openai-sentinel-so-token"] = so2
    r = s.post(AUTH + "/api/accounts/password/verify",
               json={"password": PASSWORD},
               headers=h2, allow_redirects=False, **base)
    print("[5] password", r.status_code, r.text[:600].replace("\n", " "))
except Exception:
    traceback.print_exc()
