#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Full login probe: real vs forged sentinel, + TOTP completion.
Usage: python3 _login_probe3.py <email> <password> <totp_secret> [proxy|-] [forge:0/1]
"""
import sys, os, json, uuid, importlib.util, traceback, hmac, hashlib, base64, struct, time, random
from datetime import datetime, timezone
from curl_cffi import requests as creq

EMAIL, PASSWORD, TOTP = sys.argv[1], sys.argv[2], sys.argv[3]
PROXY = sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] not in ("", "-", "none") else None
FORGE = (sys.argv[5] if len(sys.argv) > 5 else "0") == "1"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
IMP = os.environ.get("IMP", "chrome110")
CHAT, AUTH = "https://chatgpt.com", "https://auth.openai.com"

def load_sq():
    spec = importlib.util.spec_from_file_location("_sq_p", "/app/projects/chatgpt_register/steps/_sentinel_quickjs.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

sq = load_sq()
did = str(uuid.uuid4())

# --- Go-style forged sentinel (antibot.GenerateRequirementsToken) ---
def forge_token():
    sid = str(uuid.uuid4())
    perf = 1000 + random.randint(0, 49000) + random.random()
    cfg = [
        "1920x1080",
        datetime.now(timezone.utc).strftime("%a %b %d %Y %H:%M:%S GMT+0000 (Coordinated Universal Time)"),
        4294705152, 1, UA,
        "https://sentinel.openai.com/sentinel/20260219f9f6/sdk.js",
        None, None, "en-US", round(5 + random.randint(0, 45)),
        random.choice(["vendorSub-undefined","plugins-undefined","mimeTypes-undefined","hardwareConcurrency-undefined"]),
        random.choice(["location","implementation","URL","documentURI","compatMode"]),
        random.choice(["Object","Function","Array","Number","parseFloat","undefined"]),
        perf, sid, "", random.choice([4,8,12,16]),
        int(time.time()*1000) - perf,
    ]
    return "gAAAAAC" + base64.b64encode(json.dumps(cfg).encode()).decode()

def totp_now(secret):
    key = base64.b32decode(secret.upper() + "=" * ((8 - len(secret) % 8) % 8))
    counter = int(time.time()) // 30
    msg = struct.pack(">Q", counter)
    h = hmac.new(key, msg, hashlib.sha1).digest()
    o = h[-1] & 0x0f
    code = (struct.unpack(">I", h[o:o+4])[0] & 0x7fffffff) % 1000000
    return "%06d" % code

s = creq.Session()
base = {"impersonate": IMP, "timeout": 40}
if PROXY: base["proxy"] = PROXY

def sent(flow):
    if FORGE:
        t = forge_token(); print("   [forge] len=%d" % len(t)); return (t, "")
    try:
        res = sq.get_sentinel_token_via_quickjs(s, did, flow=flow, log=lambda m: print("   [sq]", m),
                                                user_agent=UA, proxy=PROXY, impersonate=IMP)
    except Exception as e:
        print("   sentinel EXC:", repr(e)[:200]); return ("", "")
    return res or ("", "")

def H(tok, so, refer):
    h = {"Content-Type": "application/json", "Origin": AUTH, "Referer": refer}
    if tok: h["openai-sentinel-token"] = tok
    if so: h["openai-sentinel-so-token"] = so
    return h

print("== target=%s forge=%s proxy=%s imp=%s" % (EMAIL, FORGE, PROXY or "DIRECT", IMP))
try:
    csrf = (s.get(CHAT + "/api/auth/csrf", **base).json() or {}).get("csrfToken", "")
    r = s.post(CHAT + "/api/auth/signin/openai",
               data={"csrfToken": csrf, "callbackUrl": "/"},
               headers={"Content-Type": "application/x-www-form-urlencoded"},
               allow_redirects=False, **base)
    authorize_url = r.headers.get("Location", "")
    r = s.get(authorize_url, allow_redirects=True, **base)
    print("[3] authorize", r.status_code, str(r.url)[:80])

    tok, so = sent("authorize_continue")
    r = s.post(AUTH + "/api/accounts/authorize/continue",
               json={"username": {"kind": "email", "value": EMAIL}},
               headers=H(tok, so, AUTH + "/log-in"), allow_redirects=False, **base)
    print("[4] continue", r.status_code, r.text[:160].replace("\n", " "))

    tok, so = sent("authorize_continue")
    r = s.post(AUTH + "/api/accounts/password/verify",
               json={"password": PASSWORD},
               headers=H(tok, so, AUTH + "/log-in/password"), allow_redirects=False, **base)
    print("[5] password", r.status_code, r.text[:300].replace("\n", " "))
    if r.status_code != 200:
        print(">>> STOP: password step failed"); sys.exit(0)
    pj = r.json() or {}
    cont = (pj.get("continue_url") or "").replace("\\/", "/")
    import re as _re
    m = _re.search(r"mfa-challenge/([0-9a-fA-F]+)", cont)
    if not m:
        print(">>> no mfa challenge; continue_url=", cont[:120]); 
    else:
        cid = m.group(1)
        print("[6] mfa challenge id", cid)
        r = s.post(AUTH + "/api/accounts/mfa/issue_challenge",
                   json={"id": cid, "type": "totp", "force_fresh_challenge": False},
                   headers=H(tok, so, AUTH + "/mfa-challenge/" + cid), allow_redirects=False, **base)
        print("[6] issue_challenge", r.status_code, r.text[:160].replace("\n", " "))
        code = totp_now(TOTP)
        r = s.post(AUTH + "/api/accounts/mfa/verify",
                   json={"id": cid, "type": "totp", "code": code},
                   headers=H(tok, so, AUTH + "/mfa-challenge/" + cid), allow_redirects=False, **base)
        print("[7] mfa/verify code=%s" % code, r.status_code, r.text[:240].replace("\n", " "))
        if r.status_code == 200:
            cont = ((r.json() or {}).get("continue_url") or cont).replace("\\/", "/")

    # follow callback
    nxt = cont
    for i in range(10):
        rr = s.get(nxt, allow_redirects=False, **base)
        l = rr.headers.get("Location", "")
        print("   [hop%d] %s %s" % (i, rr.status_code, l[:100]))
        if 300 <= rr.status_code < 400 and l:
            nxt = l if l.startswith("http") else (AUTH + l if l.startswith("/") else CHAT + l)
            continue
        break
    r = s.get(CHAT + "/api/auth/session", **base)
    j = r.json() or {}
    at = j.get("accessToken") or j.get("access_token") or ""
    print("[8] session", r.status_code, "keys=", list(j.keys())[:6])
    print(">>> ACCESS TOKEN len=%d --> %s" % (len(at), "SUCCESS" if len(at) > 100 else "NONE"))
except Exception:
    traceback.print_exc()
