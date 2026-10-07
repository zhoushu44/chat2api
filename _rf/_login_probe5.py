#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe5: login (real sentinel) once, then probe several backend-api endpoints/headers."""
import sys, os, json, uuid, importlib.util, traceback, hmac, hashlib, base64, struct, time, re as _re
from curl_cffi import requests as creq

EMAIL, PASSWORD, TOTP = sys.argv[1], sys.argv[2], sys.argv[3]
PROXY = sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] not in ("", "-", "none") else None
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
IMP = os.environ.get("IMP", "chrome110")
CHAT, AUTH = "https://chatgpt.com", "https://auth.openai.com"

spec = importlib.util.spec_from_file_location("_sq_p", "/app/projects/chatgpt_register/steps/_sentinel_quickjs.py")
sq = importlib.util.module_from_spec(spec); spec.loader.exec_module(sq)
did = str(uuid.uuid4())

def totp_now(secret):
    key = base64.b32decode(secret.upper() + "=" * ((8 - len(secret) % 8) % 8))
    h = hmac.new(key, struct.pack(">Q", int(time.time()) // 30), hashlib.sha1).digest()
    o = h[-1] & 0x0f
    return "%06d" % ((struct.unpack(">I", h[o:o+4])[0] & 0x7fffffff) % 1000000)

s = creq.Session()
base = {"impersonate": IMP, "timeout": 40}
if PROXY: base["proxy"] = PROXY

def sent(flow):
    res = sq.get_sentinel_token_via_quickjs(s, did, flow=flow, log=lambda m: None,
                                            user_agent=UA, proxy=PROXY, impersonate=IMP)
    return res or ("", "")

def H(tok, so, refer):
    h = {"Content-Type": "application/json", "Origin": AUTH, "Referer": refer}
    if tok: h["openai-sentinel-token"] = tok
    if so: h["openai-sentinel-so-token"] = so
    return h

csrf = (s.get(CHAT + "/api/auth/csrf", **base).json() or {}).get("csrfToken", "")
r = s.post(CHAT + "/api/auth/signin/openai", data={"csrfToken": csrf, "callbackUrl": "/"},
           headers={"Content-Type": "application/x-www-form-urlencoded"}, allow_redirects=False, **base)
s.get(r.headers.get("Location", ""), allow_redirects=True, **base)
tok, so = sent("authorize_continue")
s.post(AUTH + "/api/accounts/authorize/continue", json={"username": {"kind": "email", "value": EMAIL}},
       headers=H(tok, so, AUTH + "/log-in"), allow_redirects=False, **base)
tok, so = sent("authorize_continue")
r = s.post(AUTH + "/api/accounts/password/verify", json={"password": PASSWORD},
           headers=H(tok, so, AUTH + "/log-in/password"), allow_redirects=False, **base)
if r.status_code != 200:
    print("password failed", r.status_code, r.text[:200]); sys.exit(0)
cont = ((r.json() or {}).get("continue_url") or "").replace("\\/", "/")
m = _re.search(r"mfa-challenge/([0-9a-fA-F]+)", cont)
if m:
    cid = m.group(1)
    s.post(AUTH + "/api/accounts/mfa/issue_challenge", json={"id": cid, "type": "totp", "force_fresh_challenge": False},
           headers=H(tok, so, AUTH + "/mfa-challenge/" + cid), allow_redirects=False, **base)
    rr = s.post(AUTH + "/api/accounts/mfa/verify", json={"id": cid, "type": "totp", "code": totp_now(TOTP)},
                headers=H(tok, so, AUTH + "/mfa-challenge/" + cid), allow_redirects=False, **base)
    print("[mfa] verify", rr.status_code)
    if rr.status_code == 200:
        cont = ((rr.json() or {}).get("continue_url") or cont).replace("\\/", "/")
nxt = cont
for i in range(10):
    rr = s.get(nxt, allow_redirects=False, **base); l = rr.headers.get("Location", "")
    if 300 <= rr.status_code < 400 and l:
        nxt = l if l.startswith("http") else (AUTH + l if l.startswith("/") else CHAT + l); continue
    break
j = (s.get(CHAT + "/api/auth/session", **base).json() or {})
at = j.get("accessToken") or ""
acct = j.get("account") or {}
print("[session] AT len=%d plan=%s acct_id=%s" % (len(at), acct.get("planType"), acct.get("id")))

hdrs = [
    ("minimal", {"Authorization": "Bearer " + at, "Accept": "*/*", "User-Agent": UA}),
    ("full", {"Authorization": "Bearer " + at, "Accept": "*/*", "User-Agent": UA,
              "Referer": "https://chatgpt.com/", "Origin": "https://chatgpt.com",
              "oai-device-id": did, "oai-language": "en-US", "oai-client-version": "prod-2026-02-19",
              "ChatGPT-Account-ID": acct.get("id") or ""}),
]
urls = [
    "/backend-api/rate_limits?feature=image_gen",
    "/backend-api/rate_limits",
    "/backend-api/me",
    "/backend-api/accounts/check/v4-2023-04-27",
    "/backend-api/models",
]
for hname, h in hdrs:
    for u in urls:
        try:
            rr = s.get(CHAT + u, headers=h, **base)
            print("[%s] %-48s %s %s" % (hname, u, rr.status_code, rr.text[:160].replace("\n", " ")))
        except Exception as e:
            print("[%s] %-48s EXC %s" % (hname, u, repr(e)[:120]))
