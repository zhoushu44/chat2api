# -*- coding: utf-8 -*-
"""查 orchestrator 的 no_available_account 503/调度逻辑"""
import sys
sys.path.insert(0, r"e:\360MoveData\Users\Administrator\Desktop\chat2api")
from _s import run

o, e = run('grep -n "no_available_account\\|NoAvailable\\|service_unavailable" /root/chat2api/internal/protocol/*.go /root/chat2api/internal/backend/*.go 2>/dev/null | head -15', timeout=30)
print("GREP:\n", o, e[:200])

o, e = run('grep -rn "503\\|StatusServiceUnavailable" /root/chat2api/internal/protocol/*.go 2>/dev/null | head -10', timeout=30)
print("PROTO 503:\n", o, e[:200])
