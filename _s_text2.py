# -*- coding: utf-8 -*-
"""等 35s 短冷却过期后重测文本（豁免账号应恢复可调度）"""
import sys, time

sys.path.insert(0, r"e:\360MoveData\Users\Administrator\Desktop\chat2api")
from _s import run

AUTH = "zs1236547"

print("waiting 35s for short cooldown expiry ...")
time.sleep(35)

for i in range(2):
    t0 = time.time()
    o, e = run(
        "curl -s -m 120 -X POST http://127.0.0.1:3077/v1/chat/completions "
        "-H 'Content-Type: application/json' -H 'Authorization: Bearer %s' "
        "-d '{\"model\":\"gpt-4o\",\"messages\":[{\"role\":\"user\",\"content\":\"say hi in 3 words\"}]}'" % AUTH,
        timeout=150,
    )
    dt = time.time() - t0
    ok = '"content"' in o and "choices" in o
    print("  [%d/2] %s %.1fs %s" % (i + 1, "OK" if ok else "FAIL", dt, o[:120].replace("\n", " ")))
    if not ok:
        time.sleep(15)
