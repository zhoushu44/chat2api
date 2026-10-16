# -*- coding: utf-8 -*-
"""supervisorctl 不走 sock 配置 → 试 supervisorctl -c 指定配置"""
import sys
sys.path.insert(0, r"e:\360MoveData\Users\Administrator\Desktop\chat2api")
from _s import run

o, e = run("docker exec chatgpt2api-14 sh -c 'supervisorctl -c /etc/supervisor/conf.d/supervisord.conf status'", timeout=60)
print("STATUS:\n", o, e[:200])
