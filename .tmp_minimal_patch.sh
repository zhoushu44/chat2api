#!/bin/bash
set -u
# 最小超时补丁：挂死的代理引擎等 60s 也等不来，快失败快换出口
# 只改数值，不动结构/签名
cd /app/projects/chatgpt_register/steps

echo "=== _http_engine.py: OAuth 默认 60→30、首跳 75→40、后续 45→30 ==="
sed -i 's/def _oauth_get(url: str, \*, hop: int, timeout: float = 60)/def _oauth_get(url: str, *, hop: int, timeout: float = 30)/' _http_engine.py
sed -i 's/hop_timeout = 75 if hop == 0 else 45/hop_timeout = 40 if hop == 0 else 30/' _http_engine.py
sed -i 's/r = _oauth_get(cur, hop=hop + 1, timeout=45)/r = _oauth_get(cur, hop=hop + 1, timeout=30)/' _http_engine.py
echo ""
echo "=== _sentinel.py: goto 45_000→25_000 ==="
sed -i 's/timeout=45_000/timeout=25_000/g' _sentinel.py
echo ""
echo "=== step01_open_login.py: goto 60_000→25_000、email visible 30_000→25_000 ==="
sed -i 's/timeout=60_000/timeout=25_000/g' step01_open_login.py
sed -i 's/wait_for(state="visible", timeout=30_000)/wait_for(state="visible", timeout=25_000)/' step01_open_login.py
echo ""
echo "=== 校验补丁结果 ==="
grep -n "def _oauth_get" _http_engine.py
grep -n "hop_timeout" _http_engine.py
grep -n "timeout=25_000\|timeout=45_000" _sentinel.py | head -4
grep -n "timeout=25_000\|timeout=60_000" step01_open_login.py
echo ""
echo "=== 全部语法检查 ==="
python3 -c "
import ast
for f in ['_http_engine.py','_sentinel.py','step01_open_login.py','/app/proxy/wary/provider.py','/app/proxy/socks5/provider.py']:
    ast.parse(open(f if not f.startswith('/app') else f, encoding='utf-8').read())
print('ALL_SYNTAX_OK')
"
find /app -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
echo ""
echo "=== 签名完好性（set_password 还在） ==="
grep -n "set_password: bool" _http_engine.py
