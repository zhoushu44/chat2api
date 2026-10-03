#!/bin/bash
set -u
echo "=== 容器内代理环境变量 ==="
docker exec chatgpt2api-13 sh -c "env | grep -iE 'proxy|PROXY' | head -10"
echo "(none if empty)"
echo ""
echo "=== 复现空消息异常：带环境变量的 httpx ==="
cat > /tmp/test_wary2.py << 'PYEOF'
import os
print("proxy envs:", {k: v for k, v in os.environ.items() if 'proxy' in k.lower()})
import httpx, asyncio

async def main():
    url = "http://195.72.185.32:4433/api/proxies?num=1&type=json&format=n&sid=chatgpt-httpx-test-3&time=20"
    headers = {"X-API-Key": "zs1236547"}
    # 模拟 provider：client 里也带 trust_env 默认 True
    try:
        async with httpx.AsyncClient(timeout=10, headers=headers) as client:
            resp = await client.get(url)
            print("OK")
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: '{e}'")

asyncio.run(main())
PYEOF
docker cp /tmp/test_wary2.py chatgpt2api-13:/tmp/tw2.py
docker exec chatgpt2api-13 python3 /tmp/tw2.py
