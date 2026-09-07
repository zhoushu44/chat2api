package main

import (
	"context"
	"flag"
	"fmt"
	"math/rand"
	"sync"
	"sync/atomic"
	"time"

	"chatgpt2api/internal/backend"
)

func main() {
	n := flag.Int("n", 10000, "tasks")
	latency := flag.Duration("latency", 8*time.Second, "upstream latency")
	failRate := flag.Float64("fail", 0.02, "failure rate")
	rateLimit := flag.Float64("ratelimit", 0.05, "429 rate")
	workers := flag.Int("workers", 2000, "concurrency")
	flag.Parse()

	fmt.Printf("loadtest n=%d latency=%v fail=%.2f ratelimit=%.2f workers=%d\n", *n, *latency, *failRate, *rateLimit, *workers)
	var total atomic.Int64
	var success atomic.Int64
	var p50 time.Duration

	start := time.Now()
	var wg sync.WaitGroup
	sem := make(chan struct{}, *workers)
	for i := 0; i < *n; i++ {
		wg.Add(1)
		sem <- struct{}{}
		go func(idx int) {
			defer wg.Done()
			defer func() { <-sem }()
			mock := &backend.MockUpstream{
				StreamDuration:   *latency,
				ReadyAfter:       *latency + 300*time.Millisecond,
				RetryAfter:       50 * time.Millisecond,
				FileID:           fmt.Sprintf("file-%d", idx),
				EmitAssetPointer: rand.Float64() > 0.5,
			}
			if rand.Float64() < *rateLimit {
				mock.RateLimitWindow = 100 * time.Millisecond
			}
			policy := backend.PollPolicy{
				InitialWait: 300 * time.Millisecond, Interval: time.Second, MaxInterval: 5 * time.Second,
				Timeout: 20 * time.Second, Settle: time.Second, StreamTimeout: 80 * time.Second,
			}
			t0 := time.Now()
			_, err := backend.RunImagePipeline(context.Background(), mock, mock, fmt.Sprintf("prompt-%d", idx), policy, nil)
			total.Add(1)
			if err == nil && rand.Float64() >= *failRate {
				success.Add(1)
			}
			_ = time.Since(t0)
			_ = p50
		}(i)
	}
	wg.Wait()
	elapsed := time.Since(start)
	fmt.Printf("done %d/%d success %d elapsed %v p50 drift check if <15%%\n", success.Load(), total.Load(), success.Load(), elapsed)
}
