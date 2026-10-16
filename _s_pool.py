# -*- coding: utf-8 -*-
"""看 pool.go 调度段（240-280 行附近）+ orchestrator Generate 的账号等待逻辑"""
import sys
sys.path.insert(0, r"e:\360MoveData\Users\Administrator\Desktop\chat2api")
from _s import run

o, e = run('sed -n "225,290p" /root/chat2api/internal/account/pool.go', timeout=30)
print("POOL ACQUIRE:\n", o, e[:200])

o, e = run('grep -n "func (o \*Orchestrator) Generate\\|Pick\\|Acquire" /root/chat2api/internal/protocol/orchestrator.go | head', timeout=30)
print("GEN:\n", o, e[:200])
