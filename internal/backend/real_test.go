package backend

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	fhttp "github.com/bogdanfinn/fhttp"
)

// fhttpAdapter 将 fhttp.Request 转为 net/http 并用标准 client 发往 httptest。
type fhttpAdapter struct {
	client *http.Client
}

func (a *fhttpAdapter) Do(freq *fhttp.Request) (*fhttp.Response, error) {
	var bodyBytes []byte
	if freq.Body != nil {
		b, _ := io.ReadAll(freq.Body)
		bodyBytes = b
	}
	httpReq, err := http.NewRequestWithContext(freq.Context(), freq.Method, freq.URL.String(), bytes.NewReader(bodyBytes))
	if err != nil {
		return nil, err
	}
	for k, vals := range freq.Header {
		for _, v := range vals {
			httpReq.Header.Add(k, v)
		}
	}
	// 保留 Host
	if freq.URL.Host != "" {
		httpReq.Host = freq.URL.Host
	}
	resp, err := a.client.Do(httpReq)
	if err != nil {
		return nil, err
	}
	return &fhttp.Response{
		Status:        resp.Status,
		StatusCode:    resp.StatusCode,
		Proto:         resp.Proto,
		ProtoMajor:    resp.ProtoMajor,
		ProtoMinor:    resp.ProtoMinor,
		Header:        fhttp.Header(resp.Header),
		Body:          resp.Body,
		ContentLength: resp.ContentLength,
	}, nil
}

func newTestBackend(srv *httptest.Server) *Backend {
	adapter := &fhttpAdapter{client: srv.Client()}
	return NewBackendWithClient(srv.URL, "test-token", adapter)
}

func TestRealPipeline(t *testing.T) {
	var mu sync.Mutex
	convID := "conv-real-test-123"
	startTime := time.Now()
	pollCount := 0
	// pTokenSeen 记录 prepare 请求是否携带非空 p_token（P0.3：antibot PoW 链路接入证据）
	var pTokenSeen bool
	var finalizeBody map[string]any

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.Method == "GET" && r.URL.Path == "/":
			w.Header().Set("Content-Type", "text/html")
			w.WriteHeader(200)
			_, _ = w.Write([]byte(`<html><script src="/backend-api/sentinel/sdk.js"></script></html>`))
		case r.Method == "POST" && strings.HasSuffix(r.URL.Path, "/sentinel/chat-requirements/prepare"):
			var body map[string]any
			_ = json.NewDecoder(r.Body).Decode(&body)
			if p, ok := body["p"].(string); ok && p != "" {
				pTokenSeen = true
			}
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]any{
				"prepare_token": "prep-tok",
				"arkose":        map[string]any{"required": false},
				"proofofwork":   map[string]any{"required": false},
				"turnstile":     map[string]any{"required": false},
			})
		case r.Method == "POST" && strings.HasSuffix(r.URL.Path, "/sentinel/chat-requirements/finalize"):
			_ = json.NewDecoder(r.Body).Decode(&finalizeBody)
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]any{
				"token":    "sentinel-final-token",
				"so_token": "so-123",
			})
		case r.Method == "POST" && r.URL.Path == "/backend-api/f/conversation/prepare":
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]any{"conduit_token": "conduit-xyz"})
		case r.Method == "POST" && r.URL.Path == "/backend-api/f/conversation":
			w.Header().Set("Content-Type", "text/event-stream")
			w.WriteHeader(200)
			flusher, _ := w.(http.Flusher)
			// 帧 1: 中间状态
			_, _ = w.Write([]byte("data: {\"v\":{\"type\":\"delta\",\"delta\":\"generating\"}}\n\n"))
			if flusher != nil {
				flusher.Flush()
			}
			time.Sleep(20 * time.Millisecond)
			// 帧 2: asset pointer（流内快路径）
			_, _ = w.Write([]byte("data: {\"v\":{\"type\":\"tool_args\",\"arguments\":\"{\\\"asset_pointer\\\":\\\"file-service://file-abc\\\"}\"},\"conversation_id\":\"" + convID + "\"}\n\n"))
			if flusher != nil {
				flusher.Flush()
			}
			time.Sleep(10 * time.Millisecond)
			// 帧 3: 终止标记
			_, _ = w.Write([]byte("data: {\"v\":{\"message\":{\"status\":\"finished_successfully\",\"metadata\":{\"is_complete\":true}},\"conversation_id\":\"" + convID + "\"}}\n\n"))
			if flusher != nil {
				flusher.Flush()
			}
			// 保持连接一小段时间，模拟官网保持打开
			time.Sleep(50 * time.Millisecond)
		case r.Method == "GET" && strings.HasPrefix(r.URL.Path, "/backend-api/conversation/"):
			mu.Lock()
			pollCount++
			c := pollCount
			mu.Unlock()
			// 前 1 次返回 429（瞬时窗口）
			if c == 1 && time.Since(startTime) < 500*time.Millisecond {
				w.Header().Set("Retry-After", "0")
				w.WriteHeader(429)
				_, _ = w.Write([]byte(`{"detail":"rate limited"}`))
				return
			}
			// 模拟文档提交延迟：前 2 次空，后续返回 file_ids
			if c < 3 {
				w.Header().Set("Content-Type", "application/json")
				_ = json.NewEncoder(w).Encode(map[string]any{
					"mapping": map[string]any{},
				})
				return
			}
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]any{
				"mapping": map[string]any{
					"msg1": map[string]any{
						"message": map[string]any{
							"author": map[string]any{"role": "assistant"},
							"metadata": map[string]any{},
							"content": map[string]any{
								"content_type": "image_asset_pointer",
								"asset_pointer": "file-service://file-abc",
							},
							"create_time": float64(time.Now().UnixMilli()) / 1000,
						},
					},
				},
				"file_ids": []string{"file-abc"},
			})
		default:
			w.WriteHeader(404)
			_, _ = w.Write([]byte(`{"error":"not found: ` + r.URL.Path + `"}`))
		}
	}))
	defer srv.Close()

	backend := newTestBackend(srv)
	policy := PollPolicy{
		InitialWait:   5 * time.Millisecond,
		Interval:      5 * time.Millisecond,
		MaxInterval:   20 * time.Millisecond,
		Timeout:       3 * time.Second,
		Settle:        5 * time.Millisecond,
		StreamTimeout: 2 * time.Second,
	}

	// 走完整编排：GenerateImage（upload 空，bootstrap→requirements→prepare→SSE→poll）
	ctx := context.Background()
	result, err := backend.GenerateImage(ctx, "test prompt", "gpt-image-2", nil, policy)
	if err != nil {
		t.Fatalf("GenerateImage failed: %v", err)
	}
	if len(result.FileIDs) == 0 || result.FileIDs[0] != "file-abc" {
		t.Fatalf("FileIDs=%v want [file-abc]", result.FileIDs)
	}
	// StageTiming 校验
	if result.Stage.SSEStreamMs == 0 {
		t.Fatalf("SSEStreamMs=0 want >0")
	}
	// P0.3 验收：prepare 携带非空 p_token（antibot BuildLegacyRequirementsToken 接入）
	if !pTokenSeen {
		t.Fatal("prepare request did not carry non-empty p_token: antibot PoW path not wired")
	}
	// P0.3 验收：finalize 携带 prepare_token
	if ft, _ := finalizeBody["prepare_token"].(string); ft != "prep-tok" {
		t.Fatalf("finalize prepare_token=%v want prep-tok", finalizeBody["prepare_token"])
	}
	if result.Stage.PollCount < 2 {
		t.Fatalf("PollCount=%d want >=2 settle 语义", result.Stage.PollCount)
	}
	if result.Stage.TotalMs == 0 {
		t.Fatalf("TotalMs=0")
	}

	// 同时验证 RunImagePipeline 双接口路径（starter/upstream 同一 Backend）
	t.Run("RunImagePipelineDual", func(t *testing.T) {
		// 重置计数
		mu.Lock()
		pollCount = 0
		mu.Unlock()
		startTime = time.Now()
		// 使用 starter/upstream 双接口
		timing := &StageTiming{}
		policy2 := PollPolicy{
			InitialWait:   5 * time.Millisecond,
			Interval:      5 * time.Millisecond,
			MaxInterval:   20 * time.Millisecond,
			Timeout:       3 * time.Second,
			Settle:        5 * time.Millisecond,
			StreamTimeout: 2 * time.Second,
		}
		// Backend 已实现 ConversationStarter（内部会走 prepare/start），但为了独立验证
		// 使用 mock starter 保持简单：用 Backend 的 GenerateImage 已覆盖，这里仅验证 FetchConversation 429 退避
		// 直接测 PollFileIDs 的 429 退避已在 poll_test 覆盖，此处仅回归 RunImagePipeline 能跑通一套 mock
		mock := &MockUpstream{
			StreamDuration:     20 * time.Millisecond,
			ReadyAfter:         40 * time.Millisecond,
			EmitAssetPointer:   false,
			RateLimitWindow:    30 * time.Millisecond,
			RetryAfter:         10 * time.Millisecond,
			FileID:             "file-abc",
		}
		res, err := RunImagePipeline(context.Background(), mock, mock, "prompt", policy2, timing)
		if err != nil {
			t.Fatalf("RunImagePipeline mock: %v", err)
		}
		if len(res.FileIDs) == 0 {
			t.Fatalf("RunImagePipeline FileIDs empty")
		}
		if timing.PollCount == 0 {
			t.Fatalf("timing poll count 0")
		}
	})
}

func TestRealPipelineBootstrapAndRequirements(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.Method == "GET" && r.URL.Path == "/":
			w.WriteHeader(200)
			_, _ = w.Write([]byte(`ok`))
		case strings.Contains(r.URL.Path, "/prepare"):
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]any{
				"prepare_token": "pt",
				"arkose":        map[string]any{"required": false},
				"proofofwork":   map[string]any{"required": false},
				"turnstile":     map[string]any{"required": false},
			})
		case strings.Contains(r.URL.Path, "/finalize"):
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]any{"token": "tok123"})
		default:
			w.WriteHeader(200)
			_ = json.NewEncoder(w).Encode(map[string]any{})
		}
	}))
	defer srv.Close()
	backend := newTestBackend(srv)
	if err := backend.Bootstrap(context.Background()); err != nil {
		t.Fatalf("Bootstrap: %v", err)
	}
	reqs, err := backend.GetChatRequirements(context.Background())
	if err != nil {
		t.Fatalf("GetChatRequirements: %v", err)
	}
	if reqs.Token == "" {
		t.Fatalf("token empty")
	}
}

// 确保档 429 重试在 FetchConversation 返回 RetryAfter 时生效
func TestFetchConversation429(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasPrefix(r.URL.Path, "/backend-api/conversation/") {
			w.Header().Set("Retry-After", "1")
			w.WriteHeader(429)
			_, _ = w.Write([]byte(`{}`))
			return
		}
		w.WriteHeader(200)
		_, _ = w.Write([]byte(`{}`))
	}))
	defer srv.Close()
	backend := newTestBackend(srv)
	_, retryAfter, err := backend.FetchConversation(context.Background(), "conv-1")
	if err != nil {
		t.Fatalf("FetchConversation err: %v", err)
	}
	if retryAfter != time.Second {
		t.Fatalf("RetryAfter=%v want 1s", retryAfter)
	}
}

// sediment 与裸 file_ 同一 ID 不得重复计数（M1 复测：同一 ID 以两种形式出现过）。
func TestParseConversationDocSedimentBareDedupe(t *testing.T) {
	fid := "file_00000000fa28821192b76c9dbf17137b"
	docJSON := `{"mapping":{"n1":{"message":{"id":"m1","author":{"role":"tool"},"content":{"content_type":"multimodal_text","parts":[{"asset_pointer":"sediment://` + fid + `","content_type":"image_asset_pointer"}]},"metadata":{}}}}}`
	doc, err := parseConversationDoc([]byte(docJSON))
	if err != nil {
		t.Fatalf("parse err: %v", err)
	}
	if len(doc.SedimentIDs) != 1 || doc.SedimentIDs[0] != fid {
		t.Fatalf("sediment=%v want [%s]", doc.SedimentIDs, fid)
	}
	if len(doc.FileIDs) != 0 {
		t.Fatalf("fileIDs=%v want empty (bare dup of sediment)", doc.FileIDs)
	}
	// 纯裸 ID（无 URI）仍能兜底
	bareJSON := `{"mapping":{"n1":{"message":{"id":"m1","author":{"role":"assistant"},"content":{"content_type":"text","parts":["see ` + fid + `"]},"metadata":{}}}}}`
	doc2, err := parseConversationDoc([]byte(bareJSON))
	if err != nil {
		t.Fatalf("parse bare err: %v", err)
	}
	if len(doc2.FileIDs) != 1 || doc2.FileIDs[0] != fid {
		t.Fatalf("bare fileIDs=%v want [%s]", doc2.FileIDs, fid)
	}
}

// bootstrap 缓存窗口语义（OPT-3）：冷/过期/空源不复用，10 分钟内复用。
func TestBootstrapCacheFresh(t *testing.T) {
	be := &Backend{}
	if be.bootstrapFresh() {
		t.Fatal("cold backend should not be fresh")
	}
	be.scriptSources = []string{"s"}
	be.bootstrapAt = time.Now()
	if !be.bootstrapFresh() {
		t.Fatal("recent bootstrap should be fresh")
	}
	be.bootstrapAt = time.Now().Add(-11 * time.Minute)
	if be.bootstrapFresh() {
		t.Fatal("stale bootstrap should not be fresh")
	}
	be.scriptSources = nil
	be.bootstrapAt = time.Now()
	if be.bootstrapFresh() {
		t.Fatal("empty sources should not be fresh")
	}
}
