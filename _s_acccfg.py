# -*- coding: utf-8 -*-
"""看 AccountConfig json tag，改 account.concurrency=2 并重启 Go 服务"""
import sys, base64
sys.path.insert(0, r"e:\360MoveData\Users\Administrator\Desktop\chat2api")
from _s import run

o, e = run('grep -n -A10 "type AccountConfig struct" /root/chat2api/internal/config/config.go', timeout=30)
print("STRUCT:\n", o, e[:200])
