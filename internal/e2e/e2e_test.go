package e2e

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"chatgpt2api/internal/account"
	"chatgpt2api/internal/api"
	"chatgpt2api/internal/backend"
	"chatgpt2api/internal/config"
	"chatgpt2api/internal/protocol"

	"github.com/gin-gonic/gin"
	fhttp "github.com/bogdanfinn/fhttp"
)

// fhttpAdapter 复用 backend 真实测试的适配器
type fhttpAdapter struct{ c *http.Client }

func (a *fhttpAdapter) Do(req *fhttp.Request) (*fhttp.Response, error) {
	var body []byte
	if req.Body != nil {
		// 读取原始 body
		b := make([]byte, 0, 1024)
		buf := make([]byte, 1024)
		for {
			n, err := req.Body.Read(buf)
			if n > 0 {
				b = append(b, buf[:n]...)
			}
			if err != nil {
				break
			}
		}
		body = b
	}
	httpReq, _ := http.NewRequestWithContext(req.Context(), req.Method, req.URL.String(), bytes.NewReader(body))
	for k, vals := range req.Header {
		for _, v := range vals {
			httpReq.Header.Add(k, v)
		}
	}
	resp, err := a.c.Do(httpReq)
	if err != nil {
		return nil, err
	}
	return &fhttp.Response{
		Status:     resp.Status,
		StatusCode: resp.StatusCode,
		Header:     fhttp.Header(resp.Header),
		Body:       resp.Body,
	}, nil
}

// mockChatGPT 完整模拟官网所有生图相关端点
func mockChatGPT() *httptest.Server {
	var pollCount int
	convID := "conv-e2e-123"
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.Method == "GET" && r.URL.Path == "/":
			w.Write([]byte(`<html data-build="build-e2e"><script src="https://chatgpt.com/c/abc/_/sdk.js"></script></html>`))
		case strings.HasSuffix(r.URL.Path, "/sentinel/chat-requirements/prepare"):
			json.NewEncoder(w).Encode(map[string]any{
				"prepare_token": "prep-e2e",
				"arkose":        map[string]any{"required": false},
				"proofofwork":   map[string]any{"required": false},
				"turnstile":     map[string]any{"required": false},
			})
		case strings.HasSuffix(r.URL.Path, "/sentinel/chat-requirements/finalize"):
			json.NewEncoder(w).Encode(map[string]any{"token": "tok-e2e", "so_token": "so-e2e"})
		case r.URL.Path == "/backend-api/f/conversation/prepare":
			json.NewEncoder(w).Encode(map[string]any{"conduit_token": "conduit-e2e"})
		case r.URL.Path == "/backend-api/conversation" && r.Method == "POST":
			// 文本对话 SSE（P2.1）：message 增量 + [DONE]
			w.Header().Set("Content-Type", "text/event-stream")
			w.WriteHeader(200)
			flusher, _ := w.(http.Flusher)
			w.Write([]byte("data: {\"conversation_id\":\"" + convID + "\",\"message\":{\"author\":{\"role\":\"assistant\"},\"content\":{\"content_type\":\"text\",\"parts\":[\"Hello\"]}}}\n\n"))
			if flusher != nil {
				flusher.Flush()
			}
			time.Sleep(10 * time.Millisecond)
			w.Write([]byte("data: {\"conversation_id\":\"" + convID + "\",\"message\":{\"author\":{\"role\":\"assistant\"},\"content\":{\"content_type\":\"text\",\"parts\":[\"Hello world\"]}}}\n\n"))
			if flusher != nil {
				flusher.Flush()
			}
			time.Sleep(10 * time.Millisecond)
			w.Write([]byte("data: [DONE]\n\n"))
			if flusher != nil {
				flusher.Flush()
			}
		case r.URL.Path == "/backend-api/f/conversation" && r.Method == "POST":
			w.Header().Set("Content-Type", "text/event-stream")
			w.WriteHeader(200)
			flusher, _ := w.(http.Flusher)
			w.Write([]byte("data: {\"conversation_id\":\"" + convID + "\",\"v\":{\"type\":\"delta\"}}\n\n"))
			if flusher != nil {
				flusher.Flush()
			}
			time.Sleep(20 * time.Millisecond)
			w.Write([]byte("data: {\"v\":{\"message\":{\"status\":\"finished_successfully\",\"metadata\":{\"is_complete\":true}},\"conversation_id\":\"" + convID + "\"}}\n\n"))
			if flusher != nil {
				flusher.Flush()
			}
			time.Sleep(10 * time.Millisecond)
		case strings.HasPrefix(r.URL.Path, "/backend-api/conversation/"):
			pollCount++
			if pollCount == 1 {
				w.Header().Set("Retry-After", "0")
				w.WriteHeader(429)
				w.Write([]byte(`{}`))
				return
			}
			if pollCount < 3 {
				json.NewEncoder(w).Encode(map[string]any{"mapping": map[string]any{}})
				return
			}
			json.NewEncoder(w).Encode(map[string]any{
				"mapping": map[string]any{
					"msg1": map[string]any{
						"message": map[string]any{
							"author":  map[string]any{"role": "assistant"},
							"content": map[string]any{"content_type": "image_asset_pointer", "asset_pointer": "file-service://file-e2e-1"},
						},
					},
				},
				"file_ids": []string{"file-e2e-1"},
			})
		case strings.Contains(r.URL.Path, "/files") && r.Method == "POST" && !strings.Contains(r.URL.Path, "uploaded"):
			json.NewEncoder(w).Encode(map[string]any{"file_id": "file-e2e-1", "upload_url": "http://" + r.Host + "/upload"})
		case r.URL.Path == "/upload" && r.Method == "PUT":
			w.WriteHeader(200)
		case strings.Contains(r.URL.Path, "/uploaded"):
			w.WriteHeader(200)
			w.Write([]byte(`{}`))
		case strings.Contains(r.URL.Path, "/download"):
			json.NewEncoder(w).Encode(map[string]any{"download_url": "http://" + r.Host + "/image.png"})
		case r.URL.Path == "/image.png":
			w.Header().Set("Content-Type", "image/png")
			w.Write([]byte{137, 80, 78, 71}) // PNG header
		case r.URL.Path == "/backend-api/tasks":
			json.NewEncoder(w).Encode(map[string]any{"tasks": []any{}})
		default:
			json.NewEncoder(w).Encode(map[string]any{})
		}
	}))
}

func TestE2E_FullImagePipeline_RealMock(t *testing.T) {
	srv := mockChatGPT()
	defer srv.Close()

	adapter := &fhttpAdapter{c: srv.Client()}
	be := backend.NewBackendWithClient(srv.URL, "tok-e2e", adapter)

	// 测试三步上传
	png1x1 := "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII="
	ref, err := be.UploadImage(context.Background(), png1x1, "test.png")
	if err != nil {
		t.Fatalf("UploadImage: %v", err)
	}
	if ref.FileID != "file-e2e-1" {
		t.Fatalf("fileID %q", ref.FileID)
	}

	// 测试全链路 GenerateImage (含 bootstrap->requirements->prepare->SSE->poll)
	policy := backend.PollPolicy{
		InitialWait: 5 * time.Millisecond, Interval: 5 * time.Millisecond,
		MaxInterval: 20 * time.Millisecond, Timeout: 3 * time.Second,
		Settle: 5 * time.Millisecond, StreamTimeout: 2 * time.Second,
	}
	res, err := be.GenerateImage(context.Background(), "a cat", "gpt-image-2", nil, policy)
	if err != nil {
		t.Fatalf("GenerateImage: %v", err)
	}
	if len(res.FileIDs) == 0 {
		t.Fatal("no fileIDs")
	}
	if res.Stage.SSEStreamMs == 0 || res.Stage.PollCount == 0 {
		t.Fatal("StageTiming empty")
	}

	// 测试 URL 解析
	urls, err := be.ResolveImageURLs(context.Background(), "conv-e2e-123", res.FileIDs, nil)
	if err != nil {
		t.Fatalf("Resolve: %v", err)
	}
	if len(urls) == 0 {
		t.Fatal("no urls")
	}

	// 测试下载
	data, err := be.DownloadImageBytes(context.Background(), urls[0])
	if err != nil {
		t.Fatalf("Download: %v", err)
	}
	if len(data) == 0 {
		t.Fatal("empty download")
	}
}

func TestE2E_Orchestrator_WithAccountPool(t *testing.T) {
	pool := account.NewPool(nil, 5*time.Minute)
	acc := &account.Account{Token: "tok-pool", Email: "test@example.com", Type: "Plus", SourceType: "web", Status: account.StatusNormal, Quota: 10}
	pool.Add(acc)

	orch := protocol.NewOrchestrator(pool)

	// 用 mock 后端注入
	srv := mockChatGPT()
	defer srv.Close()
	adapter := &fhttpAdapter{c: srv.Client()}
	be := backend.NewBackendWithClient(srv.URL, "tok-pool", adapter)
	orch.Backends["tok-pool"] = be

	res, err := orch.Generate(context.Background(), protocol.GenerateRequest{Prompt: "a dog", Model: "gpt-image-2", N: 1})
	if err != nil {
		t.Fatalf("Orchestrator.Generate: %v", err)
	}
	if len(res.URLs) == 0 && len(res.B64) == 0 {
		t.Fatal("no result")
	}
}

// TestE2E_Orchestrator_Warmup OPT-6：mock 上游预热计数（零额度）。
func TestE2E_Orchestrator_Warmup(t *testing.T) {
	pool := account.NewPool(nil, 5*time.Minute)
	pool.Add(&account.Account{Token: "tok-pool", Email: "test@example.com", Type: "Plus", SourceType: "web", Status: account.StatusNormal, Quota: 10})
	orch := protocol.NewOrchestrator(pool)

	srv := mockChatGPT()
	defer srv.Close()
	adapter := &fhttpAdapter{c: srv.Client()}
	orch.Backends["tok-pool"] = backend.NewBackendWithClient(srv.URL, "tok-pool", adapter)

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	if n := orch.Warmup(ctx); n != 1 {
		t.Fatalf("warmed=%d want 1", n)
	}
}

// TestE2E_Orchestrator_N2_Parallel_TwoAccounts OPT-8：双号并行（mock 零额度）。
func TestE2E_Orchestrator_N2_Parallel_TwoAccounts(t *testing.T) {
	pool := account.NewPool(nil, 5*time.Minute)
	pool.Add(&account.Account{Token: "tok-a", Email: "a@example.com", Type: "Plus", SourceType: "web", Status: account.StatusNormal, Quota: 10})
	pool.Add(&account.Account{Token: "tok-b", Email: "b@example.com", Type: "Plus", SourceType: "web", Status: account.StatusNormal, Quota: 10})
	orch := protocol.NewOrchestrator(pool)

	srv := mockChatGPT()
	defer srv.Close()
	adapter := &fhttpAdapter{c: srv.Client()}
	orch.Backends["tok-a"] = backend.NewBackendWithClient(srv.URL, "tok-a", adapter)
	orch.Backends["tok-b"] = backend.NewBackendWithClient(srv.URL, "tok-b", adapter)

	res, err := orch.Generate(context.Background(), protocol.GenerateRequest{Prompt: "a dog", Model: "gpt-image-2", N: 2})
	if err != nil {
		t.Fatalf("Orchestrator.Generate N=2 parallel: %v", err)
	}
	if len(res.URLs) != 2 || len(res.B64) != 2 {
		t.Fatalf("urls=%d b64=%d want 2/2", len(res.URLs), len(res.B64))
	}
}

func TestE2E_Orchestrator_N2_Serial(t *testing.T) {	pool := account.NewPool(nil, 5*time.Minute)
	acc := &account.Account{Token: "tok-pool", Email: "test@example.com", Type: "Plus", SourceType: "web", Status: account.StatusNormal, Quota: 10}
	pool.Add(acc)

	orch := protocol.NewOrchestrator(pool)

	srv := mockChatGPT()
	defer srv.Close()
	adapter := &fhttpAdapter{c: srv.Client()}
	orch.Backends["tok-pool"] = backend.NewBackendWithClient(srv.URL, "tok-pool", adapter)

	res, err := orch.Generate(context.Background(), protocol.GenerateRequest{Prompt: "a dog", Model: "gpt-image-2", N: 2})
	if err != nil {
		t.Fatalf("Orchestrator.Generate N=2: %v", err)
	}
	if len(res.URLs) != 2 {
		t.Fatalf("urls=%d want 2 (each slot must generate independently)", len(res.URLs))
	}
	if len(res.B64) != 2 {
		t.Fatalf("b64=%d want 2", len(res.B64))
	}
}

func TestE2E_API_AllEndpoints_RealUsage(t *testing.T) {
	gin.SetMode(gin.TestMode)
	cfg, _ := config.Load("")
	cfg.DataDir = t.TempDir()
	srv := &api.Server{Cfg: cfg}
	r := srv.NewRouter()

	// P0.2 后：无 orchestrator 的 Server 对生图请求返回 503、文本请求 501（诚实而非假数据）
	tests := []struct {
		name   string
		method string
		path   string
		body   any
		isMultipart bool
		wantCode int
		check  func(*httptest.ResponseRecorder) error
	}{
		{
			name: "models",
			method: "GET", path: "/v1/models", wantCode: 200,
			check: func(w *httptest.ResponseRecorder) error {
				var out map[string]any
				json.Unmarshal(w.Body.Bytes(), &out)
				if out["object"] != "list" {
					return fmt.Errorf("object != list")
				}
				return nil
			},
		},
		{
			name: "generations no pool",
			method: "POST", path: "/v1/images/generations",
			body: map[string]any{"prompt": "a beautiful cat", "model": "gpt-image-2", "n": 2, "response_format": "b64_json"},
			wantCode: 503,
		},
		{
			name: "chat completions non-stream text no pool",
			method: "POST", path: "/v1/chat/completions",
			body: map[string]any{"model": "gpt-4o", "messages": []any{map[string]any{"role": "user", "content": "hello"}}},
			wantCode: 503,
		},
		{
			name: "messages anthropic no pool",
			method: "POST", path: "/v1/messages",
			body: map[string]any{"model": "claude-3", "messages": []any{map[string]any{"role": "user", "content": "hi"}}},
			wantCode: 503,
		},
		{
			name: "chat completions stream image no pool",
			method: "POST", path: "/v1/chat/completions",
			body: map[string]any{"model": "gpt-4o", "messages": []any{map[string]any{"role": "user", "content": "给我画一张图片：一只猫"}}, "stream": true},
			wantCode: 503,
		},
		{
			name: "chat completions stream non-image no pool",
			method: "POST", path: "/v1/chat/completions",
			body: map[string]any{"model": "gpt-4o", "messages": []any{map[string]any{"role": "user", "content": "hello"}}, "stream": true},
			wantCode: 503,
		},
		{
			name: "responses image_generation no pool",
			method: "POST", path: "/v1/responses",
			body: map[string]any{"model": "gpt-4o", "input": "draw cat", "tools": []any{map[string]any{"type": "image_generation"}}},
			wantCode: 503,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			var req *http.Request
			if tc.isMultipart {
				body := &bytes.Buffer{}
				wr := multipart.NewWriter(body)
				fw, _ := wr.CreateFormFile("image", "test.png")
				fw.Write([]byte("pngdata"))
				wr.WriteField("prompt", "edit cat to night")
				wr.Close()
				req, _ = http.NewRequest(tc.method, tc.path, body)
				req.Header.Set("Content-Type", wr.FormDataContentType())
			} else if tc.body != nil {
				b, _ := json.Marshal(tc.body)
				req, _ = http.NewRequest(tc.method, tc.path, bytes.NewReader(b))
				req.Header.Set("Content-Type", "application/json")
			} else {
				req, _ = http.NewRequest(tc.method, tc.path, nil)
			}
			w := httptest.NewRecorder()
			r.ServeHTTP(w, req)
			if w.Code != tc.wantCode {
				t.Fatalf("%s: got %d want %d body=%s", tc.name, w.Code, tc.wantCode, w.Body.String())
			}
			if tc.check != nil {
				if err := tc.check(w); err != nil {
					t.Fatalf("%s check: %v body=%s", tc.name, err, w.Body.String())
				}
			}
		})
	}
}

func TestE2E_API_Concurrent_RealUsage(t *testing.T) {
	gin.SetMode(gin.TestMode)
	cfg, _ := config.Load("")
	cfg.DataDir = t.TempDir()
	srv := &api.Server{Cfg: cfg}
	r := srv.NewRouter()

	// 100 并发生图请求：无账号池时应全部得到 503（快速失败，不假装成功）
	concurrency := 50
	total := 200
	var wg sync.WaitGroup
	errCh := make(chan error, total)
	for i := 0; i < total; i++ {
		wg.Add(1)
		go func(idx int) {
			defer wg.Done()
			body, _ := json.Marshal(map[string]any{"prompt": "cat", "n": 1})
			req, _ := http.NewRequest("POST", "/v1/images/generations", bytes.NewReader(body))
			req.Header.Set("Content-Type", "application/json")
			w := httptest.NewRecorder()
			r.ServeHTTP(w, req)
			if w.Code != 503 {
				errCh <- fmt.Errorf("code %d", w.Code)
			} else {
				errCh <- nil
			}
		}(i)
		if i%concurrency == 0 {
			time.Sleep(5 * time.Millisecond)
		}
	}
	wg.Wait()
	close(errCh)
	for err := range errCh {
		if err != nil {
			t.Fatalf("concurrent error: %v", err)
		}
	}
}

// TestE2E_API_RealImagePipeline P0.2 验收：HTTP → orchestrator → backend → mock 上游真实链路。
// 此前 /v1/images/generations 返回硬编码 tinyPNG；现在走完整服务树。
func TestE2E_API_RealImagePipeline(t *testing.T) {
	gin.SetMode(gin.TestMode)
	srv := mockChatGPT()
	defer srv.Close()

	cfg := &config.Config{DataDir: t.TempDir()}
	s := api.NewServer(cfg)
	defer s.Close()
	// 注入 mock 上游 backend 与测试账号
	acc := &account.Account{Token: "tok-pool", Email: "real@example.com", Type: "Plus", SourceType: "web", Status: account.StatusNormal, Quota: 10}
	s.Pool.Add(acc)
	adapter := &fhttpAdapter{c: srv.Client()}
	be := backend.NewBackendWithClient(srv.URL, "tok-pool", adapter)
	s.Orch.Backends["tok-pool"] = be
	r := s.NewRouter()

	// POST /v1/images/generations → 200 + 非空 b64_json（来自 mock 上游下载的图片数据）
	body, _ := json.Marshal(map[string]any{"prompt": "a cat", "model": "gpt-image-2", "n": 1, "response_format": "b64_json"})
	req, _ := http.NewRequest("POST", "/v1/images/generations", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("generations got %d want 200 body=%s", w.Code, w.Body.String())
	}
	var out struct {
		Data []struct {
			B64JSON string `json:"b64_json"`
			URL     string `json:"url"`
		} `json:"data"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &out); err != nil {
		t.Fatalf("parse response: %v", err)
	}
	if len(out.Data) != 1 {
		t.Fatalf("data len=%d want 1", len(out.Data))
	}
	if out.Data[0].B64JSON == "" || out.Data[0].B64JSON == "aVZCT1J3MEtHZ29BQUFBTlNMUUFBQUgdummy" {
		t.Fatal("b64_json empty — mock pipeline not real")
	}
	// b64 必须可解码（此前 bug：编码的是 URL 字符串而非图片数据）
	if _, err := base64.StdEncoding.DecodeString(out.Data[0].B64JSON); err != nil {
		t.Fatalf("b64_json not decodable: %v", err)
	}

	// 调用日志应已记录（logsvc 接线）
	if calls := s.LogSvc.List(); len(calls) == 0 {
		t.Fatal("logsvc empty: image attempt not logged")
	}
	// 仪表盘指标应已记录（P1.7：orchestrator → metrics.Record）
	if total := s.Metrics.Summary("24h")["total"].(map[string]any)["total"]; total != 1 {
		t.Fatalf("metrics total=%v want 1", total)
	}
}

// TestE2E_API_RealChatImagePipeline P0.2：chat completions 图片场景走真实链路。
func TestE2E_API_RealChatImagePipeline(t *testing.T) {
	gin.SetMode(gin.TestMode)
	srv := mockChatGPT()
	defer srv.Close()

	cfg := &config.Config{DataDir: t.TempDir()}
	s := api.NewServer(cfg)
	defer s.Close()
	acc := &account.Account{Token: "tok-pool", Email: "chat@example.com", Status: account.StatusNormal, Quota: 10}
	s.Pool.Add(acc)
	adapter := &fhttpAdapter{c: srv.Client()}
	s.Orch.Backends["tok-pool"] = backend.NewBackendWithClient(srv.URL, "tok-pool", adapter)
	r := s.NewRouter()

	body, _ := json.Marshal(map[string]any{"model": "gpt-4o", "messages": []any{map[string]any{"role": "user", "content": "画一张猫的图片"}}})
	req, _ := http.NewRequest("POST", "/v1/chat/completions", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("chat got %d want 200 body=%s", w.Code, w.Body.String())
	}
	var out struct {
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
		} `json:"choices"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &out); err != nil {
		t.Fatalf("parse: %v", err)
	}
	if len(out.Choices) != 1 || !strings.Contains(out.Choices[0].Message.Content, "![image](") {
		t.Fatalf("chat image content missing, got: %+v", out)
	}

	// P2.4 流式图片：progress chunks + 最终 markdown
	bodyS, _ := json.Marshal(map[string]any{"model": "gpt-4o", "messages": []any{map[string]any{"role": "user", "content": "画一张猫的图片"}}, "stream": true})
	reqS, _ := http.NewRequest("POST", "/v1/chat/completions", bytes.NewReader(bodyS))
	reqS.Header.Set("Content-Type", "application/json")
	wS := httptest.NewRecorder()
	r.ServeHTTP(wS, reqS)
	if wS.Code != 200 {
		t.Fatalf("stream chat image got %d", wS.Code)
	}
	respS := wS.Body.String()
	if !strings.Contains(respS, "uploading") {
		t.Fatalf("missing progress chunk in:\n%s", respS)
	}
	if !strings.Contains(respS, "![image](") {
		t.Fatalf("missing final image markdown in:\n%s", respS)
	}
}

// TestE2E_API_RealTextPipeline P2.1 验收：文本对话真实链路（HTTP → orch.StreamText → backend → mock 上游）。
func TestE2E_API_RealTextPipeline(t *testing.T) {
	gin.SetMode(gin.TestMode)
	srv := mockChatGPT()
	defer srv.Close()

	cfg := &config.Config{DataDir: t.TempDir()}
	s := api.NewServer(cfg)
	defer s.Close()
	acc := &account.Account{Token: "tok-pool", Email: "text@example.com", Status: account.StatusNormal, Quota: 10}
	s.Pool.Add(acc)
	adapter := &fhttpAdapter{c: srv.Client()}
	s.Orch.Backends["tok-pool"] = backend.NewBackendWithClient(srv.URL, "tok-pool", adapter)
	r := s.NewRouter()

	// 非流式：聚合 "Hello world"
	body, _ := json.Marshal(map[string]any{"model": "gpt-4o", "messages": []any{map[string]any{"role": "user", "content": "say hi"}}})
	req, _ := http.NewRequest("POST", "/v1/chat/completions", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("chat got %d want 200 body=%s", w.Code, w.Body.String())
	}
	var out struct {
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
			FinishReason string `json:"finish_reason"`
		} `json:"choices"`
		Usage map[string]any `json:"usage"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &out); err != nil {
		t.Fatalf("parse: %v", err)
	}
	if len(out.Choices) != 1 || out.Choices[0].Message.Content != "Hello world" {
		t.Fatalf("content=%+v want 'Hello world'", out.Choices)
	}
	if out.Choices[0].FinishReason != "stop" {
		t.Fatalf("finish=%q", out.Choices[0].FinishReason)
	}
	if out.Usage["total_tokens"] == nil {
		t.Fatal("usage block missing")
	}

	// 流式：首帧 role + 增量 + stop + [DONE]
	body2, _ := json.Marshal(map[string]any{"model": "gpt-4o", "messages": []any{map[string]any{"role": "user", "content": "say hi"}}, "stream": true})
	req2, _ := http.NewRequest("POST", "/v1/chat/completions", bytes.NewReader(body2))
	req2.Header.Set("Content-Type", "application/json")
	w2 := httptest.NewRecorder()
	r.ServeHTTP(w2, req2)
	if w2.Code != 200 {
		t.Fatalf("stream chat got %d body=%s", w2.Code, w2.Body.String())
	}
	resp := w2.Body.String()
	if !strings.Contains(resp, `"role":"assistant"`) {
		t.Fatalf("first frame missing role: %s", resp)
	}
	if !strings.Contains(resp, "data: [DONE]") {
		t.Fatalf("missing [DONE]: %s", resp)
	}
	if !strings.Contains(resp, `"finish_reason":"stop"`) {
		t.Fatalf("missing stop frame: %s", resp)
	}
	// 聚合验证：chunk content 拼接 == Hello world（gin SSE 写 data:{json} 无空格）
	agg := ""
	for _, line := range strings.Split(resp, "\n") {
		line = strings.TrimSpace(line)
		if !strings.HasPrefix(line, "data:") || strings.HasSuffix(line, "[DONE]") {
			continue
		}
		payload := strings.TrimSpace(strings.TrimPrefix(line, "data:"))
		var ch map[string]any
		if err := json.Unmarshal([]byte(payload), &ch); err != nil {
			continue
		}
		if choices, ok := ch["choices"].([]any); ok && len(choices) > 0 {
			if first, ok := choices[0].(map[string]any); ok {
				if delta, ok := first["delta"].(map[string]any); ok {
					if s, ok := delta["content"].(string); ok {
						agg += s
					}
				}
			}
		}
	}
	if agg != "Hello world" {
		t.Fatalf("stream aggregate=%q want 'Hello world'", agg)
	}
	// 指标记录了文本调用
	if total := s.Metrics.Summary("24h")["total"].(map[string]any)["total"]; total != 2 {
		t.Fatalf("metrics total=%v want 2", total)
	}
}

// TestE2E_API_RealMessagesPipeline P2.3 验收：anthropic messages 真实链路。
func TestE2E_API_RealMessagesPipeline(t *testing.T) {
	gin.SetMode(gin.TestMode)
	srv := mockChatGPT()
	defer srv.Close()

	cfg := &config.Config{DataDir: t.TempDir()}
	s := api.NewServer(cfg)
	defer s.Close()
	acc := &account.Account{Token: "tok-pool", Email: "msg@example.com", Status: account.StatusNormal, Quota: 10}
	s.Pool.Add(acc)
	adapter := &fhttpAdapter{c: srv.Client()}
	s.Orch.Backends["tok-pool"] = backend.NewBackendWithClient(srv.URL, "tok-pool", adapter)
	r := s.NewRouter()

	// 非流式
	body, _ := json.Marshal(map[string]any{
		"model": "claude-3", "system": "be nice",
		"messages": []any{map[string]any{"role": "user", "content": "say hi"}},
	})
	req, _ := http.NewRequest("POST", "/v1/messages", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("messages got %d body=%s", w.Code, w.Body.String())
	}
	var out struct {
		Type       string `json:"type"`
		Role       string `json:"role"`
		StopReason string `json:"stop_reason"`
		Content    []struct {
			Type string `json:"type"`
			Text string `json:"text"`
		} `json:"content"`
		Usage map[string]any `json:"usage"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &out); err != nil {
		t.Fatalf("parse: %v", err)
	}
	if out.Type != "message" || out.Role != "assistant" || out.StopReason != "end_turn" {
		t.Fatalf("envelope=%+v", out)
	}
	if len(out.Content) != 1 || out.Content[0].Text != "Hello world" {
		t.Fatalf("content=%+v", out.Content)
	}
	if out.Usage["input_tokens"] == nil {
		t.Fatal("usage missing")
	}

	// 流式：message_start → delta → message_stop
	body2, _ := json.Marshal(map[string]any{
		"model": "claude-3",
		"messages": []any{map[string]any{"role": "user", "content": []any{
			map[string]any{"type": "text", "text": "say hi"},
		}}},
		"stream": true,
	})
	req2, _ := http.NewRequest("POST", "/v1/messages", bytes.NewReader(body2))
	req2.Header.Set("Content-Type", "application/json")
	w2 := httptest.NewRecorder()
	r.ServeHTTP(w2, req2)
	if w2.Code != 200 {
		t.Fatalf("stream messages got %d", w2.Code)
	}
	resp := w2.Body.String()
	for _, ev := range []string{"message_start", "content_block_start", "content_block_delta", "content_block_stop", "message_delta", "message_stop"} {
		if !strings.Contains(resp, ev) {
			t.Fatalf("missing event %s in:\n%s", ev, resp)
		}
	}
}

// TestE2E_API_RealResponsesPipeline P2.2 验收：responses 真实链路（文本 + 图片）。
func TestE2E_API_RealResponsesPipeline(t *testing.T) {
	gin.SetMode(gin.TestMode)
	srv := mockChatGPT()
	defer srv.Close()

	cfg := &config.Config{DataDir: t.TempDir()}
	s := api.NewServer(cfg)
	defer s.Close()
	acc := &account.Account{Token: "tok-pool", Email: "resp@example.com", Status: account.StatusNormal, Quota: 10}
	s.Pool.Add(acc)
	adapter := &fhttpAdapter{c: srv.Client()}
	s.Orch.Backends["tok-pool"] = backend.NewBackendWithClient(srv.URL, "tok-pool", adapter)
	r := s.NewRouter()

	// 文本非流式：response.completed 的 output[0] 为 message
	body, _ := json.Marshal(map[string]any{"model": "gpt-4o", "input": "say hi"})
	req, _ := http.NewRequest("POST", "/v1/responses", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("responses got %d body=%s", w.Code, w.Body.String())
	}
	var out struct {
		Status string `json:"status"`
		Output []struct {
			Type    string `json:"type"`
			Content []struct {
				Type string `json:"type"`
				Text string `json:"text"`
			} `json:"content"`
		} `json:"output"`
		Usage map[string]any `json:"usage"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &out); err != nil {
		t.Fatalf("parse: %v", err)
	}
	if out.Status != "completed" || len(out.Output) != 1 || out.Output[0].Type != "message" {
		t.Fatalf("output=%+v", out)
	}
	if len(out.Output[0].Content) != 1 || out.Output[0].Content[0].Text != "Hello world" {
		t.Fatalf("text=%+v", out.Output[0].Content)
	}
	if out.Usage["total_tokens"] == nil {
		t.Fatal("usage missing")
	}

	// 文本流式：事件序列 created → delta → completed
	body2, _ := json.Marshal(map[string]any{"model": "gpt-4o", "input": "say hi", "stream": true})
	req2, _ := http.NewRequest("POST", "/v1/responses", bytes.NewReader(body2))
	req2.Header.Set("Content-Type", "application/json")
	w2 := httptest.NewRecorder()
	r.ServeHTTP(w2, req2)
	if w2.Code != 200 {
		t.Fatalf("stream responses got %d", w2.Code)
	}
	resp := w2.Body.String()
	for _, ev := range []string{"response.created", "response.output_text.delta", "response.output_text.done", "response.completed"} {
		if !strings.Contains(resp, ev) {
			t.Fatalf("missing event %s in:\n%s", ev, resp)
		}
	}

	// 图片非流式：output[0] 为 image_generation_call
	body3, _ := json.Marshal(map[string]any{
		"model": "gpt-image-2", "input": "a cat",
		"tools": []any{map[string]any{"type": "image_generation"}},
	})
	req3, _ := http.NewRequest("POST", "/v1/responses", bytes.NewReader(body3))
	req3.Header.Set("Content-Type", "application/json")
	w3 := httptest.NewRecorder()
	r.ServeHTTP(w3, req3)
	if w3.Code != 200 {
		t.Fatalf("image responses got %d body=%s", w3.Code, w3.Body.String())
	}
	var out3 struct {
		Status string `json:"status"`
		Output []struct {
			Type   string `json:"type"`
			Result string `json:"result"`
		} `json:"output"`
	}
	if err := json.Unmarshal(w3.Body.Bytes(), &out3); err != nil {
		t.Fatalf("parse: %v", err)
	}
	if out3.Status != "completed" || len(out3.Output) == 0 || out3.Output[0].Type != "image_generation_call" {
		t.Fatalf("image output=%+v", out3)
	}
	if out3.Output[0].Result == "" {
		t.Fatal("image result empty")
	}
}
