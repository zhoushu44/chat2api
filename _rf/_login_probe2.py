#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Login probe v2: full flow incl. follow to callback + /api/auth/session.
Usage: python3 _login_probe2.py <email> <password> [proxy|-] [flow_continue] [flow_pw]
"""
import sys, os, json, uuid, importlib.util, traceback
from curl_cffi import requests as creq

EMAIL = sys.argv[1]
PASSWORD = sys.argv[2]
PROXY = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] not in ("", "-", "none") else None
FLOW_C = sys.argv[4] if len(sys.argv) > 4 else "authorize_continue"
FLOW_PW = sys.argv[5] if len(sys.argv) > 5 else "authorize_continue"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
IMP = os.environ.get("IMP", "chrome131")
CHAT = "https://chatgpt.com"
AUTH = "https://auth.openai.com"

def load_sq():
    p = "/app/projects/chatgpt_register/steps/_sentinel_quickjs.py"
    spec = importlib.util.spec_from_file_location("_sq_probe", p)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

sq = load_sq()
did = str(uuid.uuid4())
print("== target=%s proxy=%s flowC=%s flowPW=%s" % (EMAIL, PROXY or "DIRECT", FLOW_C, FLOW_PW))

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
    return res or ("", "")

def hdr_openai(tok, so, refer):
    h = {"Content-Type": "application/json", "Origin": AUTH, "Referer": refer}
    if tok: h["openai-sentinel-token"] = tok
    if so: h["openai-sentinel-so-token"] = so
    return h

try:
    r = s.get(CHAT + "/api/auth/csrf", **base)
    csrf = (r.json() or {}).get("csrfToken", "")
    print("[1] csrf", r.status_code)

    r = s.post(CHAT + "/api/auth/signin/openai",
               data={"csrfToken": csrf, "callbackUrl": "/"},
               headers={"Content-Type": "application/x-www-form-urlencoded"},
               allow_redirects=False, **base)
    authorize_url = r.headers.get("Location", "")
    print("[2] signin", r.status_code, "authorize=" + authorize_url[:90])

    # follow authorize (allow redirects; record final)
    r = s.get(authorize_url, allow_redirects=True, **base)
    print("[3] authorize final", r.status_code, "final=" + str(r.url)[:110])
    print("[3] body=" + r.text[:300].replace("\n", " "))

    # continue email
    tok, so = sent(FLOW_C)
    r = s.post(AUTH + "/api/accounts/authorize/continue",
               json={"username": {"kind": "email", "value": EMAIL}},
               headers=hdr_openai(tok, so, AUTH + "/log-in"),
               allow_redirects=False, **base)
    loc_c = r.headers.get("Location", "")
    print("[4] continue", r.status_code, "loc=" + loc_c[:80], "body=" + r.text[:220].replace("\n", " "))

    # password verify
    tok2, so2 = sent(FLOW_PW)
    r = s.post(AUTH + "/api/accounts/password/verify",
               json={"password": PASSWORD},
               headers=hdr_openai(tok2, so2, AUTH + "/log-in/password"),
               allow_redirects=False, **base)
    loc_p = r.headers.get("Location", "")
    print("[5] password", r.status_code, "loc=" + loc_p[:110], "body=" + r.text[:400].replace("\n", " "))

    # follow to callback / session
    nxt = loc_p or loc_c
    if nxt and nxt.startswith("/"):
        nxt = AUTH + nxt
    if nxt:
        for i in range(8):
            rr = s.get(nxt, allow_redirects=False, **base)
            l = rr.headers.get("Location", "")
            print("   [hop%d] %s %s" % (i, rr.status_code, l[:110]))
            if 300 <= rr.status_code < 400 and l:
                nxt = l if l.startswith("http") else (AUTH + l if l.startswith("/") else CHAT + l)
                continue
            break
    r = s.get(CHAT + "/api/auth/session", **base)
    body = r.text[:400].replace("\n", " ")
    print("[6] session", r.status_code, body[:300])
    try:
        j = r.json() or {}
        at = j.get("accessToken") or j.get("access_token") or ""
        print(">>> ACCESS TOKEN len=%d  %s" % (len(at), "SUCCESS" if len(at) > 100 else "NONE"))
    except Exception as e:
        print(">>> session parse fail", e)
except Exception:
    traceback.print_exc()
