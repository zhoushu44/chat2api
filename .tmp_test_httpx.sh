#!/bin/bash
set -u
cat > /tmp/test_wary_httpx.py << 'PYEOF'
import httpx, traceback, asyncio

async def main():
    api_key = "zs1236547"
    url = "http://195.72.185.32:4433/api/proxies?num=1&type=json&format=n&sid=chatgpt-httpx-test-1&time=20"
    headers = {"X-API-Key": api_key} if api_key else {}
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=10, headers=headers) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                print(f"OK: {resp.text[:200]}")
                return
        except Exception as e:
            print(f"FAIL attempt {attempt+1}: {type(e).__name__}: '{e}'")
            traceback.print_exc()

asyncio.run(main())
PYEOF
docker cp /tmp/test_wary_httpx.py chatgpt2api-13:/tmp/tw.py
docker exec chatgpt2api-13 python3 /tmp/tw.py 2>&1 | head -25
