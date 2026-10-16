# -*- coding: utf-8 -*-
"""没有 ctl 接口 → 直接 kill uvicorn 进程（supervisord autorestart=true 会自动拉起并重载代码）。
先备份 provider.py，再写入适配 Go 版的代码，kill 29 让 supervisor 重启。"""
import sys, base64
sys.path.insert(0, r"e:\360MoveData\Users\Administrator\Desktop\chat2api")
from _s import run

# 1. 备份
o, e = run("docker exec chatgpt2api-14 cp /opt/regiforge/export/chatgpt2api/provider.py /opt/regiforge/export/chatgpt2api/provider.py.bak_gomigrate && echo BACKED_UP", timeout=60)
print("BACKUP:", o.strip(), e[:200])
