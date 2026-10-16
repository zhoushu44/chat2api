# -*- coding: utf-8 -*-
"""看 SwitchAccount：哪些失败码换号重试（哪些直接 break）"""
import sys
sys.path.insert(0, r"e:\360MoveData\Users\Administrator\Desktop\chat2api")
from _s import run

o, e = run('grep -n -B2 -A15 "func.*SwitchAccount" /root/chat2api/internal/backend/failure/classify.go', timeout=30)
print("SWITCH:\n", o, e[:200])
