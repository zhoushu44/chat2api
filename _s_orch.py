# -*- coding: utf-8 -*-
"""看 orchestrator.go 调度逻辑（在途限制/重试）"""
import sys
sys.path.insert(0, r"e:\360MoveData\Users\Administrator\Desktop\chat2api")
from _s import run

o, e = run('grep -n "inflight\\|in_flight\\|InFlight\\|semaphore\\|Sem\\|maxConcurrent\\|MaxConcurrent" /root/chat2api/internal/protocol/orchestrator.go /root/chat2api/internal/account/pool.go 2>/dev/null | head -20', timeout=30)
print("GREP:\n", o, e[:200])

o, e = run('sed -n "1,90p" /root/chat2api/internal/protocol/orchestrator.go', timeout=30)
print("ORCH:\n", o, e[:200])
