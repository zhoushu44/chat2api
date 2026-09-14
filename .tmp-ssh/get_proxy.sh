#!/bin/bash
export SSHPASS='6Qz6ao0T1zvL'
sshpass -e ssh -o StrictHostKeyChecking=no root@192.6.121.16 bash -s <<'EOF'
docker exec -i chatgpt2api-11 python - <<'PY'
import json
c = json.load(open("/opt/regiforge/data/config.json"))
p = c.get("proxy", {})
print("PROXY KEYS:", list(p.keys()) if isinstance(p, dict) else type(p))
print(json.dumps(p if not isinstance(p, dict) else {k: (v if not isinstance(v, (dict, list)) else json.dumps(v)[:300]) for k, v in p.items()}, ensure_ascii=False)[:2000])
PY
EOF
