# -*- coding: utf-8 -*-
"""看 images.go 的 503 场景（no_available_account）与调度并发限制"""
import sys
sys.path.insert(0, r"e:\360MoveData\Users\Administrator\Desktop\chat2api")
from _s import run

o, e = run('sed -n "1,120p" /root/chat2api/internal/api/v1/images.go', timeout=30)
print("IMAGES.GO:\n", o, e[:200])
