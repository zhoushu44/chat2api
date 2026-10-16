# -*- coding: utf-8 -*-
"""看 uvicorn 父进程链，确认重启方式"""
import sys
sys.path.insert(0, r"e:\360MoveData\Users\Administrator\Desktop\chat2api")
from _s import run

o, e = run("docker exec chatgpt2api-14 sh -c 'cat /proc/29/status 2>/dev/null | grep PPid; cat /proc/10/status 2>/dev/null | grep PPid; ps -ef | head -20'", timeout=60)
print("TREE:\n", o)
