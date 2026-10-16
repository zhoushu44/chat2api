# -*- coding: utf-8 -*-
"""看 generateSingle Pick 失败分支 + main 里 Orchestrator.Config 初始化"""
import sys
sys.path.insert(0, r"e:\360MoveData\Users\Administrator\Desktop\chat2api")
from _s import run

o, e = run(r'sed -n "290,380p" /root/chat2api/internal/protocol/orchestrator.go', timeout=30)
print("GEN SINGLE TAIL:\n", o, e[:200])

# 找 orchestrator 组装处（Concurrency 设置）
o, e = run('grep -rn "Config.Concurrency\\|Concurrency:" /root/chat2api/internal/ --include=*.go | grep -v _test | head', timeout=30)
print("CONC:\n", o, e[:200])
