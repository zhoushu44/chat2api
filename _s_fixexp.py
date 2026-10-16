# -*- coding: utf-8 -*-
"""探查：MailNest 余额 / RegiForge 进程 / 挂载情况"""
import sys
sys.path.insert(0, r"e:\360MoveData\Users\Administrator\Desktop\chat2api")
from _s import run

# 1. 余额
o, e = run('docker exec chatgpt2api-14 curl -s -H "Authorization: Bearer sk_xUAC_ZsIAXtDKHZzkJhpXx8QtxrorY8ASgc3xwZIoQ8" https://mailnest.top/api/v1/balance', timeout=60)
print("BALANCE:", o.strip())

# 2. RegiForge 进程
o, e = run("docker exec chatgpt2api-14 sh -c 'ps aux | grep -i -E \"uvicorn|regiforge|8787\" | grep -v grep'", timeout=60)
print("PROC:\n", o)

# 3. 挂载（/opt/regiforge 是否 volume）
o, e = run("docker inspect chatgpt2api-14 --format '{{range .Mounts}}{{.Source}} -> {{.Destination}} ({{.Type}}){{println}}{{end}}'", timeout=60)
print("MOUNTS:\n", o)
