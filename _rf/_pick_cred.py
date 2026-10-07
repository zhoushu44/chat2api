import json, sys

p = r"e:\360MoveData\Users\Administrator\Desktop\chat2api\_rf\accounts.json"
data = json.load(open(p, encoding="utf-8"))
accts = list(data.values())

want = sys.argv[1] if len(sys.argv) > 1 else None  # optional email filter
idx = int(sys.argv[2]) if len(sys.argv) > 2 else 0

cands = [a for a in accts if a.get("status") == "失效" and a.get("password") and a.get("totp_secret")]
if want:
    cands = [a for a in accts if a.get("email") == want]
if not cands:
    print("NO_MATCH")
    sys.exit(1)

a = cands[idx]
print("EMAIL=" + a["email"])
print("STATUS=" + a.get("status", ""))
print("CRED=" + a["email"] + ":" + a["password"] + ":" + a["totp_secret"])
