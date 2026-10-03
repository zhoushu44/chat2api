#!/bin/bash
# 第七轮：直接实测 warp 池出口（socks5 认证端口 10045）到 OpenAI
set -u

echo "===== A. 服务器上用 socks5 认证端口实测 auth.openai.com ====="
for P in 10045 10010 10011; do
  echo "--- warp exit port $P (socks5 auth warpuser) ---"
  timeout 30 curl -s --socks5-hostname "195.72.185.32:$P" -o /dev/null -w "auth.openai.com: HTTP %{http_code} total=%{time_total}s\n" https://auth.openai.com/ 2>&1 || echo "TIMEOUT/FAIL"
done

echo ""
echo "===== B. 实测 chatgpt.com 首页（注册流程最终目标域） ====="
timeout 30 curl -s --socks5-hostname "195.72.185.32:10045" -o /dev/null -w "chatgpt.com: HTTP %{http_code} total=%{time_total}s\n" https://chatgpt.com/ 2>&1 || echo "TIMEOUT/FAIL"
timeout 30 curl -s --socks5-hostname "195.72.185.32:10045" -o /dev/null -w "ab.chatgpt.com: HTTP %{http_code} total=%{time_total}s\n" https://ab.chatgpt.com/ 2>&1 || echo "TIMEOUT/FAIL"

echo ""
echo "===== C. 认证方式测试：socks5://warpuser:test-pass-123@ ====="
timeout 30 curl -s -x "socks5h://warpuser:test-pass-123@195.72.185.32:10045" -o /dev/null -w "auth.openai.com auth'd: HTTP %{http_code} total=%{time_total}s\n" https://auth.openai.com/ 2>&1 || echo "TIMEOUT/FAIL"

echo ""
echo "===== D. 白名单端口（11045，无认证）测试 ====="
timeout 30 curl -s --socks5-hostname "195.72.185.32:11045" -o /dev/null -w "auth.openai.com whitelist: HTTP %{http_code} total=%{time_total}s\n" https://auth.openai.com/ 2>&1 || echo "TIMEOUT/FAIL"

echo ""
echo "===== E. ipinfo 出口 IP 确认 ====="
timeout 20 curl -s --socks5-hostname "195.72.185.32:10045" https://ipinfo.io/json 2>/dev/null | head -c 300; echo ""
