#!/bin/bash
set -u
cat > /tmp/test_wary_provider.py << 'PYEOF'
import sys, asyncio, traceback, json
sys.path.insert(0, '/opt/regiforge')

from core.registry import Registry
from core.config_store import provider_config, load_config

# 与 web/task_runner 完全一致的装配
app_config = load_config()
reg = Registry()
reg.load()
wary = reg.get_proxy('wary')
cfg = provider_config(app_config, 'proxy', 'wary')
print('wary cfg keys:', sorted(cfg.keys()))
print('api_url:', cfg.get('api_url'))
print('api_key set:', bool(cfg.get('api_key')))
wary.configure(cfg)

async def main():
    try:
        info = await wary.acquire()
        print('ACQUIRE OK:', info)
    except Exception as e:
        print(f'ACQUIRE FAIL: {type(e).__name__}: {e}')
        traceback.print_exc()

asyncio.run(main())
PYEOF
docker cp /tmp/test_wary_provider.py chatgpt2api-13:/tmp/twp.py
docker exec chatgpt2api-13 python3 /tmp/twp.py 2>&1 | head -35
