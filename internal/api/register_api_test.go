package api

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"chatgpt2api/internal/config"
	"chatgpt2api/internal/register"

	"github.com/gin-gonic/gin"
)

// R3.10 注册 HTTP 端到端：鉴权矩阵 + 假 RegiForge 真建任务 + channel 三件套。
func TestRegisterAutoRefillAPI(t *testing.T) {
	gin.SetMode(gin.TestMode)
	cfg, _ := config.Load("")
	cfg.AuthKey = "secret"
	svc := register.NewWithDir(t.TempDir())

	// 假 RegiForge：建任务→task-e2e；轮询常 running；stop 计数
	var creates, stops int
	forge := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/api/tasks" && r.Method == http.MethodPost:
			creates++
			_, _ = w.Write([]byte(`{"task_id":"task-e2e"}`))
		case r.URL.Path == "/api/tasks/task-e2e/logs":
			_, _ = w.Write([]byte(`{"lines":[]}`))
		case r.URL.Path == "/api/tasks/task-e2e" && r.Method == http.MethodGet:
			_, _ = w.Write([]byte(`{"done":0,"ok":0,"failed":0,"total":15,"state":"running"}`))
		case r.URL.Path == "/api/tasks/task-e2e/stop":
			stops++
			_, _ = w.Write([]byte(`{}`))
		default:
			t.Errorf("unexpected %s %s", r.Method, r.URL.Path)
		}
	}))
	defer forge.Close()
	fc := register.NewClientFromEnv()
	fc.BaseURL = forge.URL
	fc.HTTP = forge.Client()
	svc.SetClient(fc)

	srv := &Server{Cfg: cfg, Register: svc}
	r := srv.NewRouter()
	do := func(method, path string, body any, key string) *httptest.ResponseRecorder {
		var rd *bytes.Reader
		if body != nil {
			b, _ := json.Marshal(body)
			rd = bytes.NewReader(b)
		} else {
			rd = bytes.NewReader(nil)
		}
		req, _ := http.NewRequest(method, path, rd)
		req.Header.Set("Content-Type", "application/json")
		if key != "" {
			req.Header.Set("Authorization", "Bearer "+key)
		}
		w := httptest.NewRecorder()
		r.ServeHTTP(w, req)
		return w
	}

	// 鉴权矩阵：无 key 403（对等 Python require_admin）
	if w := do("GET", "/api/register", nil, ""); w.Code != http.StatusForbidden {
		t.Fatalf("no key should be 403, got %d", w.Code)
	}
	if w := do("GET", "/api/register", nil, "wrong"); w.Code != http.StatusForbidden {
		t.Fatalf("wrong key should be 403, got %d", w.Code)
	}

	// GET 200：auto_refill 字段 + channel 三件套
	w := do("GET", "/api/register", nil, "secret")
	if w.Code != 200 {
		t.Fatalf("GET /api/register %d %s", w.Code, w.Body.String())
	}
	var resp map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &resp)
	reg := resp["register"].(map[string]any)
	for _, k := range []string{"auto_refill", "auto_refill_interval", "channel"} {
		if _, ok := reg[k]; !ok {
			t.Fatalf("%s missing %v", k, reg)
		}
	}
	ch := reg["channel"].(map[string]any)
	for _, k := range []string{"email_id", "proxy_id", "captcha_id"} {
		if ch[k] == nil || ch[k] == "" {
			t.Fatalf("channel.%s missing %v", k, ch)
		}
	}

	// POST 更新任务参数
	w = do("POST", "/api/register", map[string]any{"auto_refill": true, "auto_refill_interval": 60, "total": 20}, "secret")
	if w.Code != 200 {
		t.Fatalf("POST /api/register %d %s", w.Code, w.Body.String())
	}

	// POST start：pool 5 / total 20 → 差额 15，假 forge 真建任务
	svc.SetPoolFunc(func() int { return 5 })
	w = do("POST", "/api/register/start", nil, "secret")
	if w.Code != 200 {
		t.Fatalf("start %d %s", w.Code, w.Body.String())
	}
	_ = json.Unmarshal(w.Body.Bytes(), &resp)
	reg = resp["register"].(map[string]any)
	stats := reg["stats"].(map[string]any)
	if int(stats["running"].(float64)) != 15 {
		t.Fatalf("running plan 15 got %v", stats["running"])
	}
	if stats["task_id"] != "task-e2e" {
		t.Fatalf("task_id = %v, want task-e2e (real forge)", stats["task_id"])
	}
	if creates != 1 {
		t.Fatalf("forge creates = %d, want 1", creates)
	}

	// POST stop：远端 stop 被调一次
	w = do("POST", "/api/register/stop", nil, "secret")
	if w.Code != 200 {
		t.Fatalf("stop %d %s", w.Code, w.Body.String())
	}
	if stops != 1 {
		t.Fatalf("forge stops = %d, want 1", stops)
	}
}
