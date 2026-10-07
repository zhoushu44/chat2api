import json, collections, sys

p = "/root/chat2api/deploy/gray/data/accounts.json"
d = json.load(open(p))
items = list(d.items()) if isinstance(d, dict) else [(a.get("email"), a) for a in d]
print("total", len(items))
print("status", dict(collections.Counter(v.get("status") for k, v in items)))
seen = set()
for k, v in items:
    st = v.get("status")
    if st in seen:
        continue
    seen.add(st)
    print(json.dumps({
        "email": k, "password": v.get("password"), "totp": v.get("totp_secret"),
        "status": st, "quota": v.get("quota"),
        "exp": v.get("token_expire_at"), "len_token": len(v.get("token") or ""),
        "fp": v.get("fp"), "plan": v.get("plan_type"),
    }, ensure_ascii=True))

# also dump 3 random emails+passwords for the live test
print("TEST_SAMPLES")
for k, v in items[:3]:
    print(json.dumps([k, v.get("password"), v.get("status")], ensure_ascii=True))
