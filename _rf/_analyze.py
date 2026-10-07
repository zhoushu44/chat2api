import json, collections, sys

p = r"e:\360MoveData\Users\Administrator\Desktop\chat2api\_rf\accounts.json"
data = json.load(open(p, encoding="utf-8"))

# structure: could be list or dict with "accounts"
if isinstance(data, dict):
    accts = list(data.values())
else:
    accts = data

print("total:", len(accts))
if not accts:
    print("top-level keys:", list(data.keys())[:20] if isinstance(data, dict) else type(data))
    sys.exit()

# status counts
def g(a, k):
    return a.get(k, "") if isinstance(a, dict) else ""

print("\n== status ==")
print(collections.Counter(g(a, "status") for a in accts))
print("\n== lifecycle_status ==")
print(collections.Counter(g(a, "lifecycle_status") for a in accts))
print("\n== validity_status ==")
print(collections.Counter(g(a, "validity_status") for a in accts))

withpw = [a for a in accts if g(a, "password") and g(a, "totp_secret")]
print("\nwith password+totp:", len(withpw))
print("with password:", sum(1 for a in accts if g(a,"password")))
print("with totp:", sum(1 for a in accts if g(a,"totp_secret")))
print("with session_token:", sum(1 for a in accts if g(a,"session_token")))
print("with refresh_token:", sum(1 for a in accts if g(a,"refresh_token")))

print("\n== status of accounts WITH pw+totp ==")
print(collections.Counter(g(a, "status") for a in withpw))

# show a few disabled with pw+totp
print("\n== sample disabled accounts with pw+totp ==")
n = 0
for a in accts:
    if g(a, "status") == "失效" and g(a, "password") and g(a, "totp_secret"):
        print(json.dumps({
            "id": g(a,"id"), "email": g(a,"email"), "status": g(a,"status"),
            "lifecycle_status": g(a,"lifecycle_status"), "validity_status": g(a,"validity_status"),
            "token_len": len(g(a,"token")), "has_pw": bool(g(a,"password")),
            "has_totp": bool(g(a,"totp_secret")), "has_session": bool(g(a,"session_token")),
            "token_expire_at": g(a,"token_expire_at"),
        }, ensure_ascii=False))
        n += 1
        if n >= 8:
            break

print("\n== sample normal accounts with pw+totp ==")
n = 0
for a in accts:
    if g(a, "status") == "正常" and g(a, "password") and g(a, "totp_secret"):
        print(json.dumps({
            "id": g(a,"id"), "email": g(a,"email"), "status": g(a,"status"),
            "token_len": len(g(a,"token")), "has_session": bool(g(a,"session_token")),
            "token_expire_at": g(a,"token_expire_at"),
        }, ensure_ascii=False))
        n += 1
        if n >= 5:
            break
