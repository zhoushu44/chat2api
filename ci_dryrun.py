import sys
sys.path.insert(0, r"C:\Users\zs\Desktop\chat2api")
from ssh_run import run

cmd = r'''
echo "=== CI 构建预演（Dockerfile.single 的 Go 阶段）==="
echo "--- Dockerfile.single 关键指令 ---"
sed -n '1,20p' /tmp/c2a-push/Dockerfile.single 2>/dev/null | grep -E "FROM|COPY|RUN" | head -8
echo
echo "--- 模拟 CI：用仓库源码构建 Go 二进制 ---"
docker run --rm -v /tmp/c2a-push:/app -w /app golang:1.26-alpine sh -c '
  CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /tmp/test-ci-go ./cmd/server 2>&1 | head -10
  if [ -f /tmp/test-ci-go ]; then
    echo "CI_GO_BUILD_OK size=$(wc -c < /tmp/test-ci-go)"
    echo -n "  含 buildPostProcessRule: "; grep -c buildPostProcessRule /tmp/test-ci-go || echo 0
    echo -n "  含 thumbnail精确缩放: "; grep -c "imageMogr2/thumbnail" /tmp/test-ci-go || echo 0
    echo -n "  含超分设置UI(super_resolution): "; grep -c "super_resolution" /tmp/test-ci-go || echo 0
  else
    echo "CI_GO_BUILD_FAILED"
  fi
  rm -f /tmp/test-ci-go
'
echo
echo "=== 运行单元测试（CI 不跑，但确保不破坏）==="
docker run --rm -v /tmp/c2a-push:/app -w /app golang:1.26-alpine \
  sh -c 'go test ./internal/superres/ -run "TestPlan|TestBuild" 2>&1 | tail -3'
'''
code, out, err = run(cmd, timeout=2400)
print(out.encode("ascii","replace").decode("ascii"))
print("[exit %d]" % code)
