#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe4: real sentinel (+optional drop SO) + TOTP + rate_limits quota check.
Usage: python3 _login_probe4.py <email> <password> <totp> [proxy|-] [mode: real|noso|forge]
"""
import sys, os, json, uuid, importlib.util, traceback, hmac, hashlib, base64, struct, time, random, re as _re
from datetime import datetime, timezone
from curl_cffi import requests as creq

EMAIL, PASSWORD, TOTP = sys.argv[1], sys.argv[2], sys.argv[3]
PROXY = sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] not in ("", "-", "none") else None
MODE = sys.argv[5] if len(sys.argv) > 5 else "real"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
IMP = os.environ.get("IMP", "chrome110")
CHAT, AUTH = "https://chatgpt.com", "https://auth.openai.com"

def load_sq():
    spec = importlib.util.spec_from_file_location("_sq_p", "/app/projects/chatgpt_register/steps/_sentinel_quickjs.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
sq = load_sq()
did = str(uuid.uuid4())

def forge_token():
    sid = str(uuid.uuid4())
    perf = 1000 + random.randint(0, 49000) + random.random()
    cfg = ["1920x1080",
           datetime.now(timezone.utc).strftime("%a %b %d %Y %H:%M:%S GMT+0000 (Coordinated Universal Time)"),
           4294705152, 1, UA,
           "https://sentinel.openai.com/sentinel/20260219f9f6/sdk.js", None, None, "en-US",
           round(5 + random.randint(0, 45)),
           random.choice(["vendorSub-undefined","plugins-undefined"]),
           random.choice(["location","implementation"]),
           random.choice(["Object","Function"]),
           perf, sid, "", random.choice([4,8,12,16]), int(time.time()*1000) - perf]
    return "gAAAAAC" + base64.b64encode(json.dumps(cfg).encode()).decode()

def totp_now(secret):
    key = base64.b32decode(secret.upper() + "=" * ((8 - len(secret) % 8) % 8))
    h = hmac.new(key, struct.pack(">Q", int(time.time()) // 30), hashlib.sha1).digest()
    o = h[-1] & 0x0f
    return "%06d" % ((struct.unpack(">I", h[o:o+4])[0] & 0x7fffffff) % 1000000)

s = creq.Session()
base = {"impersonate": IMP, "timeout": 40}
if PROXY: base["proxy"] = PROXY

def sent(flow):
    if MODE == "forge":
        t = forge_token(); print("   [forge] len=%d" % len(t)); return (t, "")
    try:
        res = sq.get_sentinel_token_via_quickjs(s, did, flow=flow, log=lambda m: print("   [sq]", m),
                                                user_agent=UA, proxy=PROXY, impersonate=IMP)
    except Exception as e:
        print("   sentinel EXC:", repr(e)[:200]); return ("", "")
    res = res or ("", "")
    if MODE == "noso":
        return (res[0], "")
    return res

def H(tok, so, refer):
    h = {"Content-Type": "application/json", "Origin": AUTH, "Referer": refer}
    if tok: h["openai-sentinel-token"] = tok
    if so: h["openai-sentinel-so-token"] = so
    return h

print("== target=%s mode=%s proxy=%s" % (EMAIL, MODE, PROXY or "DIRECT"))
try:
    csrf = (s.get(CHAT + "/api/auth/csrf", **base).json() or {}).get("csrfToken", "")
    r = s.post(CHAT + "/api/auth/signin/openai", data={"csrfToken": csrf, "callbackUrl": "/"},
               headers={"Content-Type": "application/x-www-form-urlencoded"}, allow_redirects=False, **base)
    authorize_url = r.headers.get("Location", "")
    s.get(authorize_url, allow_redirects=True, **base)

    tok, so = sent("authorize_continue")
    r = s.post(AUTH + "/api/accounts/authorize/continue",
               json={"username": {"kind": "email", "value": EMAIL}},
               headers=H(tok, so, AUTH + "/log-in"), allow_redirects=False, **base)
    print("[4] continue", r.status_code, ("login_password" in r.text and "-> password page" or r.text[:80]))

    tok, so = sent("authorize_continue")
    r = s.post(AUTH + "/api/accounts/password/verify", json={"password": PASSWORD},
               headers=H(tok, so, AUTH + "/log-in/password"), allow_redirects=False, **base)
    print("[5] password", r.status_code, ("mfa_challenge" in r.text and "-> MFA" or r.text[:120].replace("\n"," ")))
    if r.status_code != 200:
        print(">>> STOP: password failed"); sys.exit(0)

    cont = ((r.json() or {}).get("continue_url") or "").replace("\\/", "/")
    m = _re.search(r"mfa-challenge/([0-9a-fA-F]+)", cont)
    if m:
        cid = m.group(1)
        s.post(AUTH + "/api/accounts/mfa/issue_challenge",
               json={"id": cid, "type": "totp", "force_fresh_challenge": False},
               headers=H(tok, so, AUTH + "/mfa-challenge/" + cid), allow_redirects=False, **base)
        code = totp_now(TOTP)
        r = s.post(AUTH + "/api/accounts/mfa/verify", json={"id": cid, "type": "totp", "code": code},
                   headers=H(tok, so, AUTH + "/mfa-challenge/" + cid), allow_redirects=False, **base)
        print("[7] mfa/verify", r.status_code)
        if r.status_code == 200:
            cont = ((r.json() or {}).get("continue_url") or cont).replace("\\/", "/")

    nxt = cont
    for i in range(10):
        rr = s.get(nxt, allow_redirects=False, **base)
        l = rr.headers.get("Location", "")
        if 300 <= rr.status_code < 400 and l:
            nxt = l if l.startswith("http") else (AUTH + l if l.startswith("/") else CHAT + l); continue
        break
    j = (s.get(CHAT + "/api/auth/session", **base).json() or {})
    at = j.get("accessToken") or j.get("access_token") or ""
    acct = j.get("account") or {}
    print("[8] ACCESS TOKEN len=%d --> %s ; plan=%s" % (len(at), "SUCCESS" if len(at) > 100 else "NONE", acct.get("planType")))

    if len(at) > 100:
        hh = {"Authorization": "Bearer " + at, "Accept": "*/*",
              "Referer": "https://chatgpt.com/", "Origin": "https://chatgpt.com",
              "User-Agent": UA, "oai-device-id": did}
        rr = s.get(CHAT + "/backend-api/rate_limits?feature=image_gen", headers=hh, **base)
        print("[9] rate_limits", rr.status_code, rr.text[:400].replace("\n", " "))
except Exception:
    traceback.print_exc()
