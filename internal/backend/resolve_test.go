package backend

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
)

// sediment 应直达 conversation 附件接口（一次命中，不再试错 files 路径）。
func TestResolveSedimentDirect(t *testing.T) {
	var attachmentHits, fileHits int64
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.Contains(r.URL.Path, "/attachment/") {
			atomic.AddInt64(&attachmentHits, 1)
			_ = json.NewEncoder(w).Encode(map[string]any{"download_url": "http://" + r.Host + "/img.png"})
			return
		}
		if strings.Contains(r.URL.Path, "/files/") {
			atomic.AddInt64(&fileHits, 1)
			w.WriteHeader(404)
			return
		}
		w.WriteHeader(404)
	}))
	defer srv.Close()

	be := NewBackendWithClient(srv.URL, "tok", &fhttpAdapter{client: srv.Client()})
	urls, err := be.ResolveImageURLs(context.Background(), "conv-1", nil, []string{"sed-1"})
	if err != nil {
		t.Fatalf("Resolve: %v", err)
	}
	if len(urls) != 1 || !strings.HasSuffix(urls[0], "/img.png") {
		t.Fatalf("urls=%v", urls)
	}
	if atomic.LoadInt64(&attachmentHits) != 1 {
		t.Fatalf("attachmentHits=%d want 1", attachmentHits)
	}
	if atomic.LoadInt64(&fileHits) != 0 {
		t.Fatalf("fileHits=%d want 0 (no files fallback on direct hit)", fileHits)
	}
}

// 附件接口 404 时回落 files 接口（保持修前可用性）。
func TestResolveSedimentFallback(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.Contains(r.URL.Path, "/attachment/") {
			w.WriteHeader(404)
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"url": "http://" + r.Host + "/img.png"})
	}))
	defer srv.Close()

	be := NewBackendWithClient(srv.URL, "tok", &fhttpAdapter{client: srv.Client()})
	urls, err := be.ResolveImageURLs(context.Background(), "conv-1", nil, []string{"sed-1"})
	if err != nil {
		t.Fatalf("Resolve fallback: %v", err)
	}
	if len(urls) != 1 {
		t.Fatalf("urls=%v", urls)
	}
}
