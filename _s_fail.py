# -*- coding: utf-8 -*-
"""查 429/502 处理 + unsupported_model 分类（429 image_quota_exhausted 映射到哪）"""
import sys
sys.path.insert(0, r"e:\360MoveData\Users\Administrator\Desktop\chat2api")
from _s import run

o, e = run('grep -rn "image_quota_exhausted\\|quota_exhausted\\|unsupported_model" /root/chat2api/internal/backend/failure/*.go /root/chat2api/internal/backend/*.go 2>/dev/null | head -15', timeout=30)
print("CLASSIFY:\n", o, e[:200])

o, e = run('grep -n -B3 -A8 "429" /root/chat2api/internal/backend/failure/failure.go 2>/dev/null | head -50', timeout=30)
print("429 MAP:\n", o, e[:300])
