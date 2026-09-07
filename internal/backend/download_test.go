package backend

import (
	"context"
	"crypto/rand"
	"net/http"
	"net/http/httptest"
	"runtime"
	"strconv"
	"testing"
	"time"
)

func TestDownload(t *testing.T) {
	// 构造 5MB 随机数据（足够测内存，又不至于太慢）
	const size = 5 * 1024 * 1024
	data := make([]byte, size)
	_, _ = rand.Read(data)

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "image/png")
		w.Header().Set("Content-Length", strconv.Itoa(size))
		// 分块写出，模拟流式
		chunk := 64 * 1024
		for i := 0; i < len(data); i += chunk {
			end := i + chunk
			if end > len(data) {
				end = len(data)
			}
			_, _ = w.Write(data[i:end])
			if f, ok := w.(http.Flusher); ok {
				f.Flush()
			}
			time.Sleep(time.Microsecond)
		}
	}))
	defer srv.Close()

	adapter := &fhttpAdapter{client: srv.Client()}
	backend := NewBackendWithClient(srv.URL, "tok", adapter)

	// 捕获下载前内存
	var m1, m2 runtime.MemStats
	runtime.GC()
	runtime.ReadMemStats(&m1)

	ctx := context.Background()
	// 并发下载 2 张（每张 5MB）
	urls := []string{srv.URL + "/img1.png", srv.URL + "/img2.png"}
	results, err := backend.DownloadImages(ctx, urls)
	if err != nil {
		t.Fatalf("DownloadImages: %v", err)
	}
	if len(results) != 2 {
		t.Fatalf("results len %d", len(results))
	}
	for i, b := range results {
		if len(b) != size {
			t.Fatalf("result %d size %d want %d", i, len(b), size)
		}
	}

	runtime.ReadMemStats(&m2)
	// 峰值内存近似：Alloc 增长不应超过 2*文件大小*并发（此处 2 张 → 20MB）
	// 由于 GC 抖动，放宽到 3 倍
	allocDelta := int64(m2.Alloc) - int64(m1.Alloc)
	limit := int64(size*2*3 + 10*1024*1024)
	if allocDelta > limit {
		t.Fatalf("memory delta %d > limit %d (possible buffering duplication)", allocDelta, limit)
	}

	// 单张流式落盘
	paths, err := backend.SaveImages(ctx, urls, t.TempDir())
	if err != nil {
		t.Fatalf("SaveImages: %v", err)
	}
	if len(paths) != 2 {
		t.Fatalf("paths %v", paths)
	}
}
