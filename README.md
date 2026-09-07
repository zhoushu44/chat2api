# ChatGPT2API Go v2.7.0

> Python v2.7.0 (27k行) → Go 单二进制（目标）。**⚠️ 骨架阶段，P0 接线已完成（2026-09-02）**——完成度审计见 [TASKS.md](TASKS.md)：`/v1` 生图已走真实链路（orchestrator→backend→antibot PoW）、面板路由与静态 SPA 已挂载、服务树在 `api.NewServer` 组装；纯文本 chat/responses 尚未实现（P2）。性能数字来自 mock 上游压测，不代表真实链路。

## 快速开始
```bash
go build -o chatgpt2api-go ./cmd/server
./chatgpt2api-go -config config.json -addr :3000
# 或 Docker
docker build -t chatgpt2api-go .
docker run -p 3000:3000 -v ./data:/data chatgpt2api-go
```

## 性能（mock 上游压测数据，非真实链路）
- 单图 P50 9.8s P95 11.2s（上游8.5s+本地1s）*仅 loadtest mock*
- 万级并发 P50漂移<5% QPS 1700+ 内存9MB 无泄漏 *仅 mock*
- 镜像 ≤50MB 启动0.08s

## 压测
```bash
go run ./cmd/m1demo
go run ./cmd/loadtest -n 10000 -latency 30ms -workers 2000
go run ./cmd/apistress
go run ./cmd/fullstress
go test ./... -cover
```

## 部署
- `STORAGE_BACKEND=json|sqlite|postgres|git|pebble`
- `CHATGPT2API_AUTH_KEY` 鉴权
- `pprof` http://127.0.0.1:6060/debug/pprof/
- `Makefile pgo-build` PGO +15% QPS
```

