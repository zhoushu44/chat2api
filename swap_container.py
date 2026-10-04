import sys
sys.path.insert(0, r"C:\Users\zs\Desktop\chat2api")
from ssh_run import run

cmd = r'''
set -e
NAME=chatgpt2api-13
echo "=== 1. 停旧容器（保留）==="
docker stop $NAME >/dev/null 2>&1
docker rename $NAME ${NAME}-v3-$(date +%H%M%S) 2>/dev/null || true
echo
echo "=== 2. 用新镜像 edfbc96344bb 启动 ==="
docker run -d --name $NAME --restart unless-stopped --init --shm-size 1g \
  -p 3077:3077 -p 6061:6060 \
  -v /root/chat2api/deploy/gray/data:/data \
  -v /root/chat2api/deploy/single/regiforge-data:/opt/regiforge/data \
  zhoushu1/chat2api:18.0 >/dev/null
sleep 10
echo
echo "=== 3. 健康检查 ==="
for i in 1 2 3 4 5 6; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 8 http://127.0.0.1:3077/v1/models -H 'Authorization: Bearer zs1236547' 2>/dev/null || echo 000)
  echo "try $i -> $code"
  [ "$code" = "200" ] && break
  sleep 5
done
echo
echo "=== 4. 前端验证 ==="
docker ps --filter name=$NAME --format '{{.Names}} | {{.Image}} | {{.Status}}'
echo "--- 首页 JS ---"
curl -s -m 10 http://127.0.0.1:3077/ | grep -oE 'index-[A-Za-z0-9_-]+\.js'
echo "--- Settings chunk + 超分字段 ---"
MAIN=$(curl -s -m 10 http://127.0.0.1:3077/ | grep -oE 'index-[A-Za-z0-9_-]+\.js' | head -1)
SC=$(curl -s -m 15 "http://127.0.0.1:3077/assets/$MAIN" | grep -oE 'Settings-[A-Za-z0-9_-]+\.js' | head -1)
echo "chunk: $SC"
if [ -n "$SC" ]; then
  body=$(curl -s -m 15 "http://127.0.0.1:3077/assets/$SC")
  echo "super_resolution: $(echo "$body" | grep -c super_resolution || true) 处"
  echo "secret_id: $(echo "$body" | grep -c secret_id || true) 处"
fi
echo
echo "=== 5. 超分配置仍在 ==="
docker exec $NAME env | grep -c SUPERRES_
'''
code, out, err = run(cmd, timeout=600)
print(out.encode("ascii","replace").decode("ascii"))
print("[exit %d]" % code)
