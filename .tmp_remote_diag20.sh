#!/bin/bash
# 第二十轮：sing-box masque 模式——认证端口与白名单端口走同一个出站，
# 为什么认证端口挂死？看一个具体实例的 singbox.json + usque 引擎状态
set -u

echo "===== A. 看一个 sid 会话实例的 singbox.json（比如 10076 对应实例 66） ====="
# 10076 - 10010 = 66 → 实例目录 warp-instances/warp-66
ls /root/warp-instances/ | head -5
echo "..."
cat /root/warp-instances/warp-66/singbox.json 2>/dev/null | python3 -m json.tool 2>/dev/null | head -60 || echo "no warp-66"

echo ""
echo "===== B. usque 引擎端口监听（enginePort 逻辑） ====="
grep -n "enginePort\|usque" /root/warp/server.js | head -15
echo "--- 本机 usque 监听端口 ---"
ss -tlnp | grep usque | head -8
ss -ulnp | grep usque | head -8

echo ""
echo "===== C. warp-66 的 usque 引擎进程是否活着 ====="
grep -n "enginePID\|engine.pid\|startUsque\|spawn.*usque" /root/warp/server.js | head -10
ls /root/warp-instances/warp-66/ 2>/dev/null
