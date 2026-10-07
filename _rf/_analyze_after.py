import json, collections

p = r"e:\360MoveData\Users\Administrator\Desktop\chat2api\_rf\accounts_after.json"
data = json.load(open(p, encoding="utf-8"))
accts = list(data.values())
print("total:", len(accts))
print("\n== status ==")
print(collections.Counter(a.get("status","") for a in accts))

# dump all keys of first account
print("\n== all keys of one account ==")
print(sorted(accts[0].keys()))

# find quota-ish keys
print("\n== keys containing quota/remaining/limit/plan ==")
ks = sorted({k for a in accts for k in a.keys() if any(w in k.lower() for w in ("quota","remain","limit","plan","expire","reset"))})
print(ks)

print("\n== normal accounts detail ==")
for a in accts:
    if a.get("status") == "正常":
        row = {k: a.get(k) for k in ks}
        row["email"] = a.get("email")
        row["token_len"] = len(a.get("token",""))
        print(json.dumps(row, ensure_ascii=False))
