// verify-accounts：存量账号 401 验活清洗工具（M4 配套）。
//
// 读 data/accounts.json（Go 格式 map[email]*Account），并发 /backend-api/me 验活；
// -prune 时把失效号标 Status=失效 并落盘（池侧 watcher 会在 5 分钟内同步移除，
// 启动加载的失效号 Available()=false 不会被 Pick）。
//
// 用法：
//
//	go run ./cmd/verify-accounts -data deploy/gray/data -proxy http://127.0.0.1:18080
//	go run ./cmd/verify-accounts -data deploy/gray/data -prune
package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"os"
	"sync"
	"time"

	"chatgpt2api/internal/account"
	"chatgpt2api/internal/backend"
)

func main() {
	dataDir := flag.String("data", "./data", "accounts.json 所在目录")
	proxy := flag.String("proxy", "", "出站代理（服务器直连留空）")
	prune := flag.Bool("prune", false, "把失效号标 Status=失效 并写回")
	concurrency := flag.Int("concurrency", 8, "并发验活数")
	timeout := flag.Duration("timeout", 30*time.Second, "单号探测超时")
	flag.Parse()

	svc := account.New(*dataDir)
	accs := svc.List()
	if len(accs) == 0 {
		log.Fatalf("no accounts under %s", *dataDir)
	}
	fmt.Printf("total=%d prune=%v concurrency=%d\n", len(accs), *prune, *concurrency)

	sem := make(chan struct{}, *concurrency)
	var mu sync.Mutex
	var bad []*account.Account
	var okN, errN int
	var wg sync.WaitGroup
	for _, a := range accs {
		wg.Add(1)
		go func(acc *account.Account) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()
			be, err := backend.NewBackend(acc.Token, acc.FP, *proxy)
			if err != nil {
				mu.Lock()
				errN++
				mu.Unlock()
				return
			}
			ctx, cancel := context.WithTimeout(context.Background(), *timeout)
			defer cancel()
			if be.VerifyToken(ctx) == nil {
				mu.Lock()
				okN++
				mu.Unlock()
				return
			}
			mu.Lock()
			bad = append(bad, acc)
			mu.Unlock()
		}(a)
	}
	wg.Wait()

	fmt.Printf("alive=%d dead=%d setup_err=%d\n", okN, len(bad), errN)
	for _, a := range bad {
		fmt.Printf("  DEAD %s\n", a.Email)
	}
	if *prune && len(bad) > 0 {
		for _, a := range bad {
			a.Status = account.StatusDisabled
			if err := svc.Add(a); err != nil {
				log.Printf("persist %s: %v", a.Email, err)
			}
		}
		fmt.Printf("pruned %d accounts (Status=失效, flushed)\n", len(bad))
	}
	_ = os.Stdout.Sync()
}
