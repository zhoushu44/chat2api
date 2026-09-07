// M1 对比演示：mock 上游（模拟官网行为）下，Python v2.7.0 轮询策略 vs Go 事件驱动策略
// 的端到端耗时对比。用于验证 10s 预算中"本地开销"部分的压缩效果。
//
// 运行：go run ./cmd/m1demo
// 上游模拟参数：生成耗时 8.5s（不可压缩），文档提交延迟 0.2s，流结束后 600ms 内轮询 429。
package main

import (
	"context"
	"fmt"
	"time"

	"chatgpt2api/internal/backend"
)

const (
	upstreamGenSecs = 8.5 // 上游生成耗时（不可压缩的物理下限）
	docCommitLag    = 200 * time.Millisecond
	rateLimitWindow = 600 * time.Millisecond
)

func pythonPolicy() backend.PollPolicy {
	// Python v2.7.0 默认值（config.py:453-465）
	return backend.PollPolicy{
		InitialWait:   10 * time.Second, // image_poll_initial_wait_secs
		Interval:      10 * time.Second, // image_poll_interval_secs
		MaxInterval:   10 * time.Second,
		Timeout:       60 * time.Second,
		Settle:        5 * time.Second, // image_settle_secs
		StreamTimeout: 80 * time.Second,
	}
}

func goPolicy() backend.PollPolicy {
	// Go 版默认值（internal/config）
	return backend.PollPolicy{
		InitialWait:   300 * time.Millisecond,
		Interval:      time.Second,
		MaxInterval:   5 * time.Second,
		Timeout:       60 * time.Second,
		Settle:        time.Second,
		StreamTimeout: 80 * time.Second,
	}
}

func main() {
	scenarios := []struct {
		name      string
		policy    backend.PollPolicy
		streamIDs bool // SSE 流内是否携带 asset pointer（官网偶发行为）
	}{
		{"Python v2.7.0 策略（盲等10s/间隔10s/settle5s）", pythonPolicy(), false},
		{"Go 事件驱动策略（0.3s/自适应1-5s/settle1s）", goPolicy(), false},
		{"Go 事件驱动 + 流内asset pointer（快路径）", goPolicy(), true},
	}

	fmt.Printf("上游模拟：生成耗时 %.1fs（不可压缩）｜文档提交延迟 %v｜流结束后 %v 内轮询返回429+Retry-After 1s\n\n",
		upstreamGenSecs, docCommitLag, rateLimitWindow)
	fmt.Printf("%-46s %10s %10s %10s %6s %10s %12s\n",
		"场景", "SSE流", "首次等待", "轮询等待", "次数", "端到端", "本地开销")

	for _, sc := range scenarios {
		ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
		mock := &backend.MockUpstream{
			StreamDuration:  time.Duration(upstreamGenSecs * float64(time.Second)),
			ReadyAfter:      time.Duration(upstreamGenSecs*float64(time.Second)) + docCommitLag,
			EmitAssetPointer: sc.streamIDs,
			RateLimitWindow: rateLimitWindow,
			RetryAfter:      time.Second,
			FileID:          "file-demo-001",
		}
		timing := &backend.StageTiming{}
		start := time.Now()
		result, err := backend.RunImagePipeline(ctx, mock, mock, "一只漂浮在太空里的猫", sc.policy, timing)
		cancel()
		if err != nil {
			fmt.Printf("%-46s 失败: %v\n", sc.name, err)
			continue
		}
		total := time.Since(start)
		overhead := total - time.Duration(upstreamGenSecs*float64(time.Second))
		fmt.Printf("%-46s %10s %10s %10s %6d %10s %12s\n",
			sc.name,
			fmt.Sprintf("%.1fs", float64(timing.SSEStreamMs)/1000),
			fmt.Sprintf("%.1fs", float64(timing.InitialWaitMs)/1000),
			fmt.Sprintf("%.1fs", float64(timing.PollWaitMs)/1000),
			timing.PollCount,
			total.Round(100*time.Millisecond),
			overhead.Round(100*time.Millisecond))
		_ = result
	}

	fmt.Println("\n说明：SSE流耗时=上游生成时间（两种策略相同）；本地开销=端到端-上游耗时，即调度策略造成的浪费。")
	fmt.Println("Python 版实测最低 30s 时，上游生成约 8~9s + 本地开销 15~22s；Go 策略将本地开销压缩到 1~3s。")
}
