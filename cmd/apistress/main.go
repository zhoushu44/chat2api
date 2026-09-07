package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"runtime"
	"sync"
	"sync/atomic"
	"time"

	"chatgpt2api/internal/api"
	"chatgpt2api/internal/config"

	"github.com/gin-gonic/gin"
)

func main() {
	gin.SetMode(gin.ReleaseMode)
	cfg, _ := config.Load("")
	srv := &api.Server{Cfg: cfg}
	r := srv.NewRouter()

	// 压测参数
	concurrency := 500
	totalRequests := 5000

	fmt.Printf("API 压测: concurrency=%d total=%d\n", concurrency, totalRequests)

	var wg sync.WaitGroup
	sem := make(chan struct{}, concurrency)
	var success atomic.Int64
	var failed atomic.Int64
	var sumLatency atomic.Int64

	start := time.Now()
	var mBefore, mAfter runtime.MemStats
	runtime.GC()
	runtime.ReadMemStats(&mBefore)

	for i := 0; i < totalRequests; i++ {
		wg.Add(1)
		sem <- struct{}{}
		go func(idx int) {
			defer wg.Done()
			defer func() { <-sem }()
			t0 := time.Now()
			// 随机选择端点，模拟真实使用
			var req *http.Request
			switch idx % 5 {
			case 0:
				body, _ := json.Marshal(map[string]any{"prompt": fmt.Sprintf("cat %d", idx), "n": 1, "model": "gpt-image-2"})
				req, _ = http.NewRequest("POST", "/v1/images/generations", bytes.NewReader(body))
			case 1:
				body, _ := json.Marshal(map[string]any{"model": "gpt-4o", "messages": []any{map[string]any{"role": "user", "content": "hello"}}})
				req, _ = http.NewRequest("POST", "/v1/chat/completions", bytes.NewReader(body))
			case 2:
				body, _ := json.Marshal(map[string]any{"model": "gpt-image-2", "prompt": "edit test", "image": "data:image/png;base64,iVBORw0KGgo="})
				req, _ = http.NewRequest("POST", "/v1/images/edits", bytes.NewReader(body))
			case 3:
				req, _ = http.NewRequest("GET", "/v1/models", nil)
			case 4:
				body, _ := json.Marshal(map[string]any{"model": "gpt-4o", "input": "test", "tools": []any{map[string]any{"type": "image_generation"}}})
				req, _ = http.NewRequest("POST", "/v1/responses", bytes.NewReader(body))
			}
			req.Header.Set("Content-Type", "application/json")
			w := httptest.NewRecorder()
			r.ServeHTTP(w, req)
			lat := time.Since(t0)
			sumLatency.Add(int64(lat))
			if w.Code >= 200 && w.Code < 300 {
				success.Add(1)
			} else {
				failed.Add(1)
			}
		}(i)
	}
	wg.Wait()
	elapsed := time.Since(start)
	runtime.ReadMemStats(&mAfter)

	avgLatency := time.Duration(sumLatency.Load() / int64(totalRequests))
	memDeltaMB := float64(mAfter.Alloc-mBefore.Alloc) / 1024 / 1024
	if mAfter.Alloc < mBefore.Alloc {
		memDeltaMB = float64(mAfter.Alloc) / 1024 / 1024
	}
	fmt.Printf("完成: success=%d failed=%d elapsed=%v avgLatency=%v\n", success.Load(), failed.Load(), elapsed, avgLatency)
	fmt.Printf("QPS=%.1f 内存增量=%.1fMB 当前Alloc=%.1fMB NumGoroutine=%d\n", float64(totalRequests)/elapsed.Seconds(), memDeltaMB, float64(mAfter.Alloc)/1024/1024, runtime.NumGoroutine())
	fmt.Printf("P50 估算 avgLatency 漂移检查: 基准~5ms, 实测 %v\n", avgLatency)
	if failed.Load() > 0 {
		fmt.Printf("WARN: 有失败请求 %d\n", failed.Load())
	} else {
		fmt.Printf("PASS: 全部成功\n")
	}
	// 超高压力下检查是否 OOM / 泄漏
	if memDeltaMB > 500 {
		fmt.Printf("FAIL: 内存泄漏嫌疑 >500MB\n")
	} else {
		fmt.Printf("PASS: 内存稳定\n")
	}
	if runtime.NumGoroutine() > 1000 {
		fmt.Printf("WARN: goroutine 可能泄漏: %d\n", runtime.NumGoroutine())
	} else {
		fmt.Printf("PASS: goroutine 无泄漏\n")
	}
}
