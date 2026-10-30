"""从历史日志回填账号统计字段（单号产出 / 存活）。

用法（容器内执行）：
    docker exec chatgpt2api-14 python3 /opt/chat2api/tools/backfill_account_stats.py

做两件事：
1. 解析 /data/image_attempts.jsonl，统计每个账号的成功/失败次数与首末活动时间；
2. 回填到 /data/accounts.json 的 images_ok / images_fail / created_at / last_seen；
   并用 last_seen 估算已死账号的 died_at。

幂等：只在字段缺失或可改进时写入，重复执行安全。会先备份 accounts.json。
"""
from __future__ import annotations

import collections
import datetime
import json
import shutil
import sys

LOG = "/data/image_attempts.jsonl"
ACC = "/data/accounts.json"


def parse_ts(s):
    try:
        return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def main() -> int:
    ok_by = collections.Counter()
    fail_by = collections.Counter()
    first_seen: dict[str, float] = {}
    last_seen: dict[str, float] = {}

    n = 0
    try:
        f = open(LOG, encoding="utf-8", errors="ignore")
    except FileNotFoundError:
        print(f"日志不存在：{LOG}")
        return 1
    with f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                d = json.loads(ln)
            except Exception:
                continue
            n += 1
            ts = parse_ts(d.get("created_at"))
            status = d.get("status")
            atts = d.get("attempts") or []
            succ = None
            for a in atts:
                aid = a.get("account_id") or ""
                if not aid:
                    continue
                if str(a.get("code") or "").lower() in ("ok", "success", ""):
                    succ = aid
                if ts:
                    if aid not in first_seen or ts < first_seen[aid]:
                        first_seen[aid] = ts
                    if aid not in last_seen or ts > last_seen[aid]:
                        last_seen[aid] = ts
            if status == "success" and succ:
                ok_by[succ] += 1
            elif status != "success" and atts:
                aid = atts[-1].get("account_id") or ""
                if aid:
                    fail_by[aid] += 1

    print(f"解析日志行={n}")
    print(f"有成功产出账号={len(ok_by)} 总成功={sum(ok_by.values())}")
    print(f"有失败账号={len(fail_by)} 总失败={sum(fail_by.values())}")

    bak = ACC + ".bak_stats_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(ACC, bak)
    print(f"已备份 -> {bak}")

    d = json.load(open(ACC))
    items = d if isinstance(d, list) else list(d.values())
    ok_hit = died_hit = 0
    for a in items:
        key = a.get("id") or a.get("email")
        em = a.get("email")
        ok = ok_by.get(key, 0) or ok_by.get(em, 0)
        fl = fail_by.get(key, 0) or fail_by.get(em, 0)
        if ok:
            a["images_ok"] = ok
            ok_hit += 1
        if fl:
            a["images_fail"] = fl
        fs = first_seen.get(key) or first_seen.get(em)
        if fs:
            cur = a.get("created_at") or 0
            if cur == 0 or cur > fs:
                a["created_at"] = int(fs)
        ls = last_seen.get(key) or last_seen.get(em)
        if ls:
            a["last_seen"] = int(ls)
            # 已死但无死亡时间：用最后活动时间估算
            if a.get("status") == "失效" and not a.get("died_at"):
                ca = a.get("created_at")
                if ca and ls > ca:
                    a["died_at"] = int(ls)
                    died_hit += 1

    json.dump(d if isinstance(d, dict) else items, open(ACC, "w"), ensure_ascii=False, indent=2)
    print(f"回填完成：产出命中 {ok_hit}/{len(items)}，死亡时间估算 {died_hit}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
