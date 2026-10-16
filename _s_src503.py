# -*- coding: utf-8 -*-
"""看 503/429/400 的具体响应内容（bench.py 需要记录 body）——重跑小批并保存完整响应"""
import sys, base64
sys.path.insert(0, r"e:\360MoveData\Users\Administrator\Desktop\chat2api")
from _s import run

# 直接单发一次看错误结构：先看 Go 源码里 503 是什么场景
o, e = run('docker exec chatgpt2api-14 sh -c "grep -rn \\"503\\" /data/ 2>/dev/null | head; true"', timeout=30)
print("LOCAL /data grep:", o[:300])

# host 源码：503 相关
o, e = run('grep -rn "503\\|StatusServiceUnavailable" /root/chat2api/internal/api/v1/images.go /root/chat2api/internal/ 2>/dev/null | head -20', timeout=30)
print("SRC 503:\n", o[:2000], e[:200])
