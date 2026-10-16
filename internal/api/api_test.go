package api

import (
	"bytes"
	"encoding/json"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"testing"

	"chatgpt2api/internal/config"

	"github.com/gin-gonic/gin"
)

// P0.2 后：/v1 生图路由无 orchestrator 时返回 503（服务未组装），
// 纯文本 chat/responses 返回 501（未实现，不再假装成功返回 "hello"）。
func TestAPIRoutes_NoOrchestrator(t *testing.T) {
	gin.SetMode(gin.TestMode)
	cfg, _ := config.Load("")
	cfg.DataDir = t.TempDir()
	s := &Server{Cfg: cfg}
	r := s.NewRouter()
	tests := []struct {
		method, path string
		body         any
		want         int
	}{
		{"GET", "/healthz", nil, 200},
		{"GET", "/v1/models", nil, 200},
		{"POST", "/v1/images/generations", map[string]any{"prompt": "cat", "n": 1}, 503},
		{"POST", "/v1/images/edits", map[string]any{"prompt": "cat"}, 503},
		{"POST", "/v1/chat/completions", map[string]any{"model": "gpt-4o", "messages": []any{map[string]any{"role": "user", "content": "hello"}}}, 503},
		{"POST", "/v1/responses", map[string]any{"tools": []any{map[string]any{"type": "image_generation"}}, "input": "x"}, 503},
		{"POST", "/v1/messages", map[string]any{"model": "claude"}, 503},
	}
	for _, tc := range tests {
		var body *bytes.Reader
		if tc.body != nil {
			b, _ := json.Marshal(tc.body)
			body = bytes.NewReader(b)
		} else {
			body = bytes.NewReader(nil)
		}
		req, _ := http.NewRequest(tc.method, tc.path, body)
		req.Header.Set("Content-Type", "application/json")
		w := httptest.NewRecorder()
		r.ServeHTTP(w, req)
		if w.Code != tc.want {
			t.Errorf("%s %s got %d want %d body=%s", tc.method, tc.path, w.Code, tc.want, w.Body.String())
		}
	}
}

func TestImagesEditsMultipart_NoOrchestrator(t *testing.T) {
	gin.SetMode(gin.TestMode)
	cfg, _ := config.Load("")
	cfg.DataDir = t.TempDir()
	s := &Server{Cfg: cfg}
	r := s.NewRouter()
	body := &bytes.Buffer{}
	wr := multipart.NewWriter(body)
	fw, _ := wr.CreateFormFile("image", "test.png")
	_, _ = fw.Write([]byte("pngdata"))
	wr.Close()
	req, _ := http.NewRequest("POST", "/v1/images/edits", body)
	req.Header.Set("Content-Type", wr.FormDataContentType())
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code != 503 {
		t.Fatalf("got %d want 503", w.Code)
	}
}

// TestAPIAuth_PrefixRejected P0.5：Bearer 前缀弱匹配已改为精确匹配。
// "Bearer keyX-extra" 不得通过 "Bearer keyX" 鉴权。
func TestAPIAuth_PrefixRejected(t *testing.T) {
	gin.SetMode(gin.TestMode)
	cfg := &config.Config{AuthKey: "sk-test-key-123", DataDir: t.TempDir()}
	s := &Server{Cfg: cfg}
	r := s.NewRouter()
	// 正确 key
	req, _ := http.NewRequest("GET", "/v1/models", nil)
	req.Header.Set("Authorization", "Bearer sk-test-key-123")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("exact key got %d want 200", w.Code)
	}
	// 前缀伪造：此前 HasPrefix 会放过，现在必须 401
	req2, _ := http.NewRequest("GET", "/v1/models", nil)
	req2.Header.Set("Authorization", "Bearer sk-test-key-123-forged")
	w2 := httptest.NewRecorder()
	r.ServeHTTP(w2, req2)
	if w2.Code != 401 {
		t.Fatalf("prefix-forged key got %d want 401", w2.Code)
	}
}

// TestAPICORS P0.5：CORS 头存在，OPTIONS 预检 204。
func TestAPICORS(t *testing.T) {
	gin.SetMode(gin.TestMode)
	cfg, _ := config.Load("")
	cfg.DataDir = t.TempDir()
	s := &Server{Cfg: cfg}
	r := s.NewRouter()
	req, _ := http.NewRequest("OPTIONS", "/v1/models", nil)
	req.Header.Set("Origin", "https://panel.example.com")
	req.Header.Set("Access-Control-Request-Method", "POST")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code != 204 {
		t.Fatalf("preflight got %d want 204", w.Code)
	}
	if w.Header().Get("Access-Control-Allow-Origin") != "https://panel.example.com" {
		t.Fatalf("CORS origin header missing: %v", w.Header())
	}
}

// TestAPIStaticMounted P0.4：web_dist SPA fallback 生效（此前 RegisterStatic 从未被调用）。
func TestAPIStaticMounted(t *testing.T) {
	gin.SetMode(gin.TestMode)
	cfg, _ := config.Load("")
	cfg.DataDir = t.TempDir()
	s := &Server{Cfg: cfg}
	r := s.NewRouter()
	// 未知路径 → SPA fallback 返回 index.html（200）
	req, _ := http.NewRequest("GET", "/some/spa/route", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code == 404 {
		t.Fatal("SPA fallback not mounted: got 404")
	}
	// _ 开头文件不会被 //go:embed 目录模式嵌入（Go 显式排除 _/. 前缀），Vite 公共 chunk 必须能拿到 JS，否则 import 整链失败
	req, _ = http.NewRequest("GET", "/assets/_plugin-vue_export-helper-DlAUqK2U.js", nil)
	w = httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("underscore chunk got %d want 200", w.Code)
	}
	if ct := w.Header().Get("Content-Type"); ct != "text/javascript; charset=utf-8" {
		t.Fatalf("underscore chunk content-type=%q want javascript (likely SPA fallback swallowing 404)", ct)
	}
}

// TestAPIAdminMounted P0.4：/api/accounts 面板路由挂载（此前死代码）。
func TestAPIAdminMounted(t *testing.T) {
	gin.SetMode(gin.TestMode)
	cfg, _ := config.Load("")
	cfg.DataDir = t.TempDir()
	s := NewServer(cfg)
	defer s.Close()
	r := s.NewRouter()
	req, _ := http.NewRequest("GET", "/api/accounts", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("/api/accounts got %d want 200 body=%s", w.Code, w.Body.String())
	}
}

// TestNewServer_OrchestratorWired P0.1：NewServer 组装的服务树可用。
func TestNewServer_OrchestratorWired(t *testing.T) {
	gin.SetMode(gin.TestMode)
	cfg := &config.Config{DataDir: t.TempDir()}
	s := NewServer(cfg)
	defer s.Close()
	if s.Orch == nil || s.Pool == nil || s.Accounts == nil || s.LogSvc == nil || s.Tasks == nil || s.Prompts == nil {
		t.Fatal("NewServer service tree incomplete")
	}
	if s.Catalog == nil || s.Metrics == nil {
		t.Fatal("NewServer missing catalog/metrics (P1.4/P1.7)")
	}
}

// TestDashboard P1.7：/api/dashboard 返回指标汇总 + 账号健康度。
func TestDashboard(t *testing.T) {
	gin.SetMode(gin.TestMode)
	cfg := &config.Config{DataDir: t.TempDir()}
	s := NewServer(cfg)
	defer s.Close()
	r := s.NewRouter()
	// 无账号 → degraded
	req, _ := http.NewRequest("GET", "/api/dashboard?time_range=24h", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("dashboard got %d", w.Code)
	}
	var out map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &out); err != nil {
		t.Fatal(err)
	}
	if out["status"] != "degraded" || out["healthy"] != false {
		t.Fatalf("no-account dashboard should degrade: %v", out)
	}
	m, _ := out["metrics"].(map[string]any)
	if m["time_range"] != "24h" {
		t.Fatalf("metrics time_range=%v", m)
	}
	// 非法 time_range → 400
	req2, _ := http.NewRequest("GET", "/api/dashboard?time_range=1y", nil)
	w2 := httptest.NewRecorder()
	r.ServeHTTP(w2, req2)
	if w2.Code != 400 {
		t.Fatalf("bad time_range got %d want 400", w2.Code)
	}
}

// TestUserKeyAuthV1 P2.6：用户密钥可访问 /v1，但不可访问 /api（须 admin）。
func TestUserKeyAuthV1(t *testing.T) {
	gin.SetMode(gin.TestMode)
	cfg := &config.Config{AuthKey: "sk-master", DataDir: t.TempDir()}
	s := NewServer(cfg)
	defer s.Close()
	_, userRaw, err := s.Auth.CreateKey("user", "u1")
	if err != nil {
		t.Fatal(err)
	}
	_, adminRaw, err := s.Auth.CreateKey("admin", "a1")
	if err != nil {
		t.Fatal(err)
	}
	r := s.NewRouter()
	get := func(path, key string) int {
		req, _ := http.NewRequest("GET", path, nil)
		if key != "" {
			req.Header.Set("Authorization", "Bearer "+key)
		}
		w := httptest.NewRecorder()
		r.ServeHTTP(w, req)
		return w.Code
	}
	// /v1：主密钥、用户密钥、admin 密钥均可；错密钥 401
	if get("/v1/models", "sk-master") != 200 {
		t.Fatal("master key rejected on /v1")
	}
	if get("/v1/models", userRaw) != 200 {
		t.Fatal("user key rejected on /v1")
	}
	if get("/v1/models", adminRaw) != 200 {
		t.Fatal("admin key rejected on /v1")
	}
	if get("/v1/models", "sk-wrong") != 401 {
		t.Fatal("wrong key should 401 on /v1")
	}
	// /api：主密钥与 admin 密钥可；用户密钥 403；无密钥 403（有鉴权配置时）
	if get("/api/prompts", "sk-master") != 200 {
		t.Fatal("master key rejected on /api")
	}
	if get("/api/prompts", adminRaw) != 200 {
		t.Fatal("admin key rejected on /api")
	}
	if get("/api/prompts", userRaw) != 403 {
		t.Fatal("user key should 403 on /api")
	}
	if get("/api/prompts", "") != 403 {
		t.Fatal("anonymous should 403 on /api when auth configured")
	}
}

// TestAuthUsersCRUD P2.6：/api/auth/users 四端点。
func TestAuthUsersCRUD(t *testing.T) {
	gin.SetMode(gin.TestMode)
	cfg := &config.Config{AuthKey: "sk-master", DataDir: t.TempDir()}
	s := NewServer(cfg)
	defer s.Close()
	r := s.NewRouter()
	call := func(method, path, key, body string) (int, map[string]any) {
		var reader *bytes.Reader
		if body != "" {
			reader = bytes.NewReader([]byte(body))
		} else {
			reader = bytes.NewReader(nil)
		}
		req, _ := http.NewRequest(method, path, reader)
		req.Header.Set("Content-Type", "application/json")
		if key != "" {
			req.Header.Set("Authorization", "Bearer "+key)
		}
		w := httptest.NewRecorder()
		r.ServeHTTP(w, req)
		var out map[string]any
		_ = json.Unmarshal(w.Body.Bytes(), &out)
		return w.Code, out
	}
	// 未鉴权 → 403
	if code, _ := call("GET", "/api/auth/users", "", ""); code != 403 {
		t.Fatalf("anonymous users list got %d", code)
	}
	// 创建
	code, out := call("POST", "/api/auth/users", "sk-master", `{"name":"api-user"}`)
	if code != 200 {
		t.Fatalf("create got %d %v", code, out)
	}
	raw, _ := out["key"].(string)
	if raw == "" {
		t.Fatal("no raw key returned")
	}
	item, _ := out["item"].(map[string]any)
	id, _ := item["id"].(string)
	if id == "" {
		t.Fatalf("no id: %v", out)
	}
	// 新密钥可访问 /v1
	req, _ := http.NewRequest("GET", "/v1/models", nil)
	req.Header.Set("Authorization", "Bearer "+raw)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("new user key rejected: %d", w.Code)
	}
	// 列表
	if code, out := call("GET", "/api/auth/users", "sk-master", ""); code != 200 || len(out["items"].([]any)) != 1 {
		t.Fatalf("list got %d %v", code, out)
	}
	// 空更新 → 400
	if code, _ := call("POST", "/api/auth/users/"+id, "sk-master", `{}`); code != 400 {
		t.Fatalf("empty update got %d", code)
	}
	// 禁用
	if code, _ := call("POST", "/api/auth/users/"+id, "sk-master", `{"enabled":false}`); code != 200 {
		t.Fatalf("disable got %d", code)
	}
	req2, _ := http.NewRequest("GET", "/v1/models", nil)
	req2.Header.Set("Authorization", "Bearer "+raw)
	w2 := httptest.NewRecorder()
	r.ServeHTTP(w2, req2)
	if w2.Code != 401 {
		t.Fatalf("disabled key should 401, got %d", w2.Code)
	}
	// 删除
	if code, _ := call("DELETE", "/api/auth/users/"+id, "sk-master", ""); code != 200 {
		t.Fatalf("delete got %d", code)
	}
	if code, _ := call("DELETE", "/api/auth/users/"+id, "sk-master", ""); code != 404 {
		t.Fatalf("re-delete got %d", code)
	}
}
