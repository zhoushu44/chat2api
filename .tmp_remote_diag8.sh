#!/bin/bash
# 第八轮：TCP 层定位 —— warp 池端口从「服务器本机」到「容器内」的连通性差异
set -u

echo "===== A. 本机 TCP 连 warp 池端口 ====="
for P in 10045 10010 11045; do
  timeout 5 bash -c "echo > /dev/tcp/195.72.185.32/$P" 2>/dev/null && echo "TCP $P: OK" || echo "TCP $P: FAIL"
done

echo ""
echo "===== B. 容器内 TCP 连 warp 池端口 ====="
for P in 10045 10010 11045; do
  docker exec chatgpt2api-13 timeout 5 python3 -c "
import socket
s=socket.socket(); s.settimeout(4)
try:
    s.connect(('195.72.185.32', $P)); print('TCP $P in-container: OK')
except Exception as e:
    print('TCP $P in-container: FAIL', e)
s.close()" 2>&1
done

echo ""
echo "===== C. 服务器 curl 到 socks5 端口的详细错误 ====="
curl -v --socks5-hostname "195.72.185.32:10045" --max-time 20 https://ipinfo.io/json 2>&1 | grep -E "^[<>*]|error|refused|timed|SOCKS" | head -15

echo ""
echo "===== D. warp 容器详情（是否 network_mode host，端口映射） ====="
docker inspect warp --format '{{.HostConfig.NetworkMode}} | ports: {{json .HostConfig.PortBindings}}' 2>/dev/null
docker inspect warp --format '{{json .NetworkSettings.Networks}}' 2>/dev/null | head -c 400; echo ""

echo ""
echo "===== E. warp 容器自身日志错误 ====="
docker logs warp --tail 30 2>&1 | grep -iE "error|fail|refus|timeout|403|denied" | tail -15

echo ""
echo "===== F. proxypilot（代理池管理）日志尾部 ====="
docker logs proxypilot --tail 40 2>&1 | tail -30
