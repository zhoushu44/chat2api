# PGO 构建：先压测采集 default.pgo，再用 -pgo 编译，+15% QPS
PGO ?= default.pgo

build:
	go build -o chatgpt2api-go ./cmd/server

# P2.9 运维命令
tools:
	go build -o bin/init-proxy-config ./cmd/init-proxy-config
	go build -o bin/migrate-storage ./cmd/migrate-storage
	go build -o bin/verify-oauth-refresh ./cmd/verify-oauth-refresh

# P2.10 回归：构建 + vet + 全量测试
regress:
	go build ./... && go vet ./... && go test ./...

pgo-build: $(PGO)
	go build -pgo=$(PGO) -o chatgpt2api-go ./cmd/server

$(PGO):
	go run ./cmd/loadtest -n 5000 -latency 50ms -workers 2000
	go run ./cmd/apistress
	# 采集 pprof
	curl -s http://localhost:3000/debug/pprof/profile?seconds=10 > $(PGO) || echo "no pprof, using empty"

pprof:
	go tool pprof -http=:8080 http://localhost:3000/debug/pprof/heap

bench:
	go test -bench=. -benchmem ./... | tee bench.txt
