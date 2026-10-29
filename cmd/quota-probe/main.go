// quota_probe 一次性只读额度探测工具：验证 refresh.go 的真实上游探测能力。
// 默认只打印脱敏结果，不写 accounts.json、不启动调度器。
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"os"
	"time"

	"chatgpt2api/internal/backend"
)

type probeAccount struct {
	Email string            `json:"email"`
	Token string            `json:"token"`
	FP    map[string]string `json:"fp"`
}

func main() {
	email := flag.String("email", "", "账号邮箱")
	token := flag.String("token", "", "账号 access_token")
	proxy := flag.String("proxy", "", "出站代理")
	timeout := flag.Duration("timeout", 35*time.Second, "探测超时")
	flag.Parse()
	if *email == "" || *token == "" {
		log.Fatal("需要 -email 与 -token（仅用于一次性只读探测）")
	}
	be, err := backend.NewBackend(*token, nil, *proxy)
	if err != nil {
		log.Fatalf("create backend: %v", err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), *timeout)
	defer cancel()
	started := time.Now()
	quota, err := be.FetchAccountQuota(ctx)
	result := map[string]any{
		"email":      *email,
		"elapsed_ms": time.Since(started).Milliseconds(),
		"ok":         quota.OK,
		"quota":      quota.Quota,
		"plan_type":  quota.PlanType,
	}
	if err != nil {
		result["error"] = err.Error()
	}
	encoded, _ := json.Marshal(result)
	fmt.Println(string(encoded))
	if err != nil {
		os.Exit(2)
	}
}
