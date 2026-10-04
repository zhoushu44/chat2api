import sys, time
sys.path.insert(0, r"C:\Users\zs\Desktop\chat2api")
from ssh_run import run

print("=== 1. 二进制大小对比（应比之前的 30498978 大，因 embed 了新前端）===")
code, out, err = run("ls -la /tmp/c2a-push/chatgpt2api-go-new | awk '{print $5}'", timeout=60)
print("new binary:", out.strip())

print("\n=== 2. 更新容器（复用安全部署逻辑，旧容器仍保留）===")
code, out, err = run(r'''
NAME=chatgpt2api-13
STAMP=$(date +%Y%m%d-%H%M%S)
# 停当前 18.0 容器（改名保留）
docker stop $NAME >/dev/null 2>&1
docker rename $NAME ${NAME}-v1-$STAMP
# 启新容器（同配置）
docker run -d --name $NAME --restart unless-stopped --init --shm-size 1g \
  -p 3077:3077 -p 6061:6060 \
  -v /root/chat2api/deploy/gray/data:/data \
  -v /root/chat2api/deploy/single/regiforge-data:/opt/regiforge/data \
  zhoushu1/chat2api:18.0 >/dev/null && echo STARTED
sleep 8
# 健康检查
for i in 1 2 3 4 5 6; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 8 http://127.0.0.1:3077/v1/models -H 'Authorization: Bearer zs1236547' 2>/dev/null || echo 000)
  echo "try $i -> $code"
  [ "$code" = "200" ] && break
  sleep 5
done
echo
echo "=== 3. 验证新前端已上线（首页应引用新 JS）==="
curl -s -m 10 http://127.0.0.1:3077/ | grep -oE 'index-[A-Za-z0-9_-]+\.js'
echo
echo "=== 4. Settings chunk 是否可访问且含超分UI ==="
SC=$(curl -s -m 10 http://127.0.0.1:3077/ | grep -oE 'index-[A-Za-z0-9_-]+\.js' | head -1)
# 拿主JS找 Settings chunk 名
NEW_SC=$(curl -s -m 15 http://127.0.0.1:3077/assets/$SC | grep -oE '"Settings-[A-Za-z0-9_-]+\.js"' | head -1 | tr -d '"')
echo "Settings chunk: $NEW_SC"
if [ -n "$NEW_SC" ]; then
  n=$(curl -s -m 15 "http://127.0.0.1:3077/assets/$NEW_SC" | grep -c super_resolution)
  echo "super_resolution in serving chunk: $n 处"
fi
''', timeout=600)
print(out.encode("ascii","replace").decode("ascii"))
print("[exit %d]" % code)
