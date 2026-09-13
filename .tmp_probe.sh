#!/bin/sh
echo "=== 服务器 regiforge 的 proxy 配置 ==="
sed -n '/"proxy"/,/^  }/p' /opt/regiforge/data/config.json 2>/dev/null | head -80
echo "=== wary 段 ==="
grep -B2 -A 8 '"wary"' /opt/regiforge/data/config.json 2>/dev/null
