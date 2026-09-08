// qa-text：一次性实测 free 号文本对话可用性与额度（钉第一个 normal 号连发）。
// 输出：每发 http/耗时/文本长度或错误；遇限流类错误即停并统计。
package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"strings"
	"time"

	"chatgpt2api/internal/account"
	"chatgpt2api/internal/backend"
	"chatgpt2api/internal/protocol"
)

func main() {
	dataDir := flag.String("data", "./data", "accounts.json 目录")
	proxy := flag.String("proxy", "", "出站代理")
	model := flag.String("model", "auto", "文本模型 slug")
	max := flag.Int("max", 15, "最大发数")
	rounds := flag.String("prompts", "", "多轮对话：| 分隔各轮 user 内容（启用多轮上下文累积；max 自动=轮数）")
	email := flag.String("email", "", "钉指定账号（不填=池内第一个 normal）")
	flag.Parse()

	svc := account.New(*dataDir)
	var target *account.Account
	for _, a := range svc.List() {
		if a.Status != account.StatusNormal {
			continue
		}
		if *email != "" && a.Email != *email {
			continue
		}
		target = a
		break
	}
	if target == nil {
		fmt.Println("no normal account (or email not found)")
		os.Exit(1)
	}
	fmt.Printf("target=%s model=%s\n", target.Email, *model)

	var promptList []string
	if *rounds != "" {
		promptList = strings.Split(*rounds, "|")
		for i := range promptList {
			promptList[i] = strings.TrimSpace(promptList[i])
		}
		fmt.Printf("rounds=%d\n", len(promptList))
	} else {
		promptList = []string{"reply with exactly: ok"}
	}
	limit := *max
	if *rounds != "" {
		limit = len(promptList)
	}

	be, err := backend.NewBackend(target.Token, target.FP, *proxy)
	if err != nil {
		fmt.Println("backend err", err)
		os.Exit(1)
	}
	var history []map[string]any
	for i := 1; i <= limit; i++ {
		q := promptList[(i-1)%len(promptList)]
		ctx, cancel := context.WithTimeout(context.Background(), 240*time.Second)
		start := time.Now()
		reqs, err := be.GetChatRequirements(ctx)
		if err != nil {
			fmt.Printf("#%02d requirements err %v (%.0fs)\n", i, err, time.Since(start).Seconds())
			cancel()
			break
		}
		history = append(history, map[string]any{"role": "user", "content": q})
		body, err := be.StartTextConversation(ctx, history, *model, "", reqs)
		if err != nil {
			fmt.Printf("#%02d start err: %v (%.0fs)\n", i, err, time.Since(start).Seconds())
			cancel()
			break
		}
		var sb strings.Builder
		upstreamModel := ""
		parser := protocol.NewTextStreamParser("")
		convID, streamErr := backend.StreamTextPayloads(ctx, body, 200*time.Second, func(p string) {
			if delta := parser.Feed(p); delta != "" {
				sb.WriteString(delta)
			}
			// 上游实际 model_slug（确认请求 slug 是否被真路由）
			if upstreamModel == "" {
				if idx := strings.Index(p, `"model_slug":"`); idx >= 0 {
					rest := p[idx+len(`"model_slug":"`):]
					if end := strings.Index(rest, `"`); end >= 0 {
						upstreamModel = rest[:end]
					}
				}
			}
		})
		el := time.Since(start).Seconds()
		msg := strings.TrimSpace(sb.String())
		if len(msg) > 400 {
			msg = msg[:400] + "…"
		}
		status := "ok"
		if streamErr != nil {
			status = "ERR:" + truncateErr(streamErr.Error(), 160)
		}
		fmt.Printf("#%02d [Q] %s\n     [A] %s\n     [conv=%s %ds %s upstream=%s]\n", i, q, msg, convID[:8], int(el), status, upstreamModel)
		cancel()
		low := strings.ToLower(status)
		if strings.Contains(low, "rate") || strings.Contains(low, "limit") || strings.Contains(low, "quota") || strings.Contains(low, "429") || strings.Contains(low, "too many") || strings.Contains(low, "err:") {
			fmt.Println("STOP on error/limit")
			break
		}
		if *rounds == "" {
			time.Sleep(3 * time.Second)
		}
	}
	fmt.Println("done")
}

func truncateErr(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n] + "…"
}
