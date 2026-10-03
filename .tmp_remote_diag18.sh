#!/bin/bash
# 找 warp server.js 里认证端口的实现
grep -n "auth" /root/warp/server.js | head -40
echo "====="
grep -n "10000\|base_port\|authPort\|auth_port\|portOffset\|port_offset" /root/warp/server.js | head -20
echo "====="
grep -n "username\|password" /root/warp/server.js | head -30
