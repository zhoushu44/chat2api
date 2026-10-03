#!/bin/bash
set -u
cat > /tmp/test_wary3.py << 'PYEOF'
import sys, asyncio, traceback
sys.path.insert(0, '/opt/regiforge')
# 复现 task_runner 的 provider 装配
import json
app_config = json.load(open('/opt/regiforge/data/config.json'))

def provider_config(cfg, kind, pid):
    # task_runner 里是 provider_config(app_config, "proxy", config.proxy_id)
    # 简化复现：projects 段里有 provider 覆盖吗？
    import importlib
    mod = importlib.import_module('core.config_store')
    # 真实实现可能不同，直接看配置结构
    return None

# 直接用 registry 装配（与 web.app 相同路径）
from core.registry import Registry
reg = Registry()
reg.load()

wary = reg.get_proxy('wary')
# 与 task_runner 相同：provider_config(app_config, "proxy", "wary")
from core.task_runner import provider_config if False else None
PYEOF
echo "=== 看 task_runner 里 provider_config 怎么实现 ==="
docker exec chatgpt2api-13 grep -n "def provider_config" -A 25 /opt/regiforge/core/task_runner.py | head -35
