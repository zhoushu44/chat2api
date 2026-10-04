import sys, time
sys.path.insert(0, r"C:\Users\zs\Desktop\chat2api")
from ssh_run import run

cmd = r'''
set -e
echo "=== 1. 确认镜像构建目录的二进制是新的 ==="
md5sum /tmp/c2a-push/chatgpt2api-go-new /root/c2a-verify/chatgpt2api-go
echo
echo "=== 2. 同步新二进制并强制重建镜像（--no-cache）==="
cp /tmp/c2a-push/chatgpt2api-go-new /root/c2a-verify/chatgpt2api-go
docker build --no-cache -q -t zhoushu1/chat2api:18.0 /root/c2a-verify 2>&1 | tail -2
echo
echo "=== 3. 验证镜像内二进制 md5 ==="
docker run --rm zhoushu1/chat2api:18.0 md5sum /chatgpt2api-go 2>/dev/null || \
docker create --name vchk zhoushu1/chat2api:18.0 >/dev/null && \
docker cp vchk:/chatgpt2api-go /tmp/go_in_img 2>/dev/null && \
md5sum /tmp/go_in_img && docker rm vchk >/dev/null
echo
echo "=== 4. 更新容器 ==="
NAME=chatgpt2api-13
STAMP=$(date +%Y%m%d-%H%M%S)
docker stop $NAME >/dev/null 2>&1
docker rename $NAME ${NAME}-v2-$STAMP
docker run -d --name $NAME --restart unless-stopped --init --shm-size 1g \
  -p 3077:3077 -p 6061:6060 \
  -v /root/chat2api/deploy/gray/data:/data \
  -v /root/chat2api/deploy/single/regiforge-data:/opt/regiforge/data \
  zhoushu1/chat2api:18.0 >/dev/null && echo STARTED
sleep 8
echo
echo "=== 5. 健康检查 + 前端验证 ==="
for i in 1 2 3 4 5; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 8 http://127.0.0.1:3077/v1/models -H 'Authorization: Bearer zs1236547' 2>/dev/null || echo 000)
  [ "$code" = "200" ] && echo "health: 200 OK" && break
  sleep 5
done
echo
echo "--- 首页引用的 JS（应为新 hash）---"
curl -s -m 10 http://127.0.0.1:3077/ | grep -oE 'index-[A-Za-z0-9_-]+\.js'
echo "--- Settings chunk 可达性 ---"
MAIN=$(curl -s -m 10 http://127.0.0.1:3077/ | grep -oE 'index-[A-Za-z0-9_-]+\.js' | head -1)
SC=$(curl -s -m 15 "http://127.0.0.1:3077/assets/$MAIN" | grep -oE 'Settings-[A-Za-z0-9_-]+\.js' | head -1)
echo "Settings chunk: $SC"
if [ -n "$SC" ]; then
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 15 "http://127.0.0.1:3077/assets/$SC")
  echo "  -> HTTP $code"
fi
'''
code, out, err = run(cmd, timeout=900)
print(out.encode("ascii","replace").decode("ascii"))
print("[exit %d]" % code)
