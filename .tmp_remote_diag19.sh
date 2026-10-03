#!/bin/bash
# 看 buildSingboxConfig 的 inbounds 结构 —— 认证端口 vs 白名单端口差异
sed -n '1232,1340p' /root/warp/server.js
