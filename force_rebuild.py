import sys, time
sys.path.insert(0, r"C:\Users\zs\Desktop\chat2api")
from ssh_run import run

print("=== 强制重编译 embed 包（清 web_dist 缓存）===")
code, out, err = run(
    "docker run --rm -v /tmp/c2a-push:/app -w /app golang:1.26-alpine sh -c '"
    "rm -rf /app/.gocache && "
    "go clean -cache 2>/dev/null; "
    "CGO_ENABLED=0 go build -trimpath -ldflags=\"-s -w\" -o /app/chatgpt2api-go-new ./cmd/server && "
    "echo REBUILD_OK && ls -la /app/chatgpt2api-go-new | awk \"{print \\$5}\"'", timeout=3600)
print(out.encode("ascii","replace").decode("ascii"))
print("[exit %d]" % code)
