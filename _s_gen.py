# -*- coding: utf-8 -*-
"""看 Generate 里 Pick 失败后的处理（等待重试 or 直接失败）"""
import sys
sys.path.insert(0, r"e:\360MoveData\Users\Administrator\Desktop\chat2api")
from _s import run

o, e = run(r'sed -n "166,290p" /root/chat2api/internal/protocol/orchestrator.go', timeout=30)
print("GENERATE:\n", o, e[:200])
