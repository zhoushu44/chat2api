package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"chatgpt2api/internal/config"

	"github.com/gin-gonic/gin"
)

// R4.8 面板登录：login 正确放行/错误 401；status 永不 401。
func TestAuthPanelLoginStatus(t *testing.T) {
	gin.SetMode(gin.TestMode)
	cfg, _ := config.Load("")
	cfg.AuthKey = "secret"
	srv := &Server{Cfg: cfg}
	r := srv.NewRouter()
	do := func(method, path, key string) *httptest.ResponseRecorder {
		req, _ := http.NewRequest(method, path, nil)
		if key != "" {
			req.Header.Set("Authorization", "Bearer "+key)
		}
		w := httptest.NewRecorder()
		r.ServeHTTP(w, req)
		return w
	}
	// login 正确密钥
	w := do("POST", "/auth/login", "secret")
	if w.Code != 200 {
		t.Fatalf("login %d %s", w.Code, w.Body.String())
	}
	var resp map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &resp)
	if resp["authenticated"] != true || resp["role"] != "admin" || resp["home_route"] != "/" {
		t.Fatalf("login view = %v", resp)
	}
	// login 错误密钥 → 401（面板据此显示“密钥无效”）
	w = do("POST", "/auth/login", "wrong")
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("wrong key login should be 401, got %d", w.Code)
	}
	// status 无密钥 → 200 + authenticated:false（对等 Python 永不 401）
	w = do("GET", "/auth/status", "")
	if w.Code != 200 {
		t.Fatalf("status %d", w.Code)
	}
	_ = json.Unmarshal(w.Body.Bytes(), &resp)
	if resp["authenticated"] != false || resp["role"] != nil {
		t.Fatalf("anon status = %v", resp)
	}
	// status 带密钥 → admin 视图 + capabilities
	w = do("GET", "/auth/status", "secret")
	_ = json.Unmarshal(w.Body.Bytes(), &resp)
	if resp["authenticated"] != true {
		t.Fatalf("status = %v", resp)
	}
	caps := resp["capabilities"].(map[string]any)
	if caps["admin_console"] != true || caps["studio"] != true {
		t.Fatalf("capabilities = %v", caps)
	}
}
