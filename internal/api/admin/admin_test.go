package admin

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"chatgpt2api/internal/account"
	"chatgpt2api/internal/config"

	"github.com/gin-gonic/gin"
)

func TestAdminAccounts(t *testing.T) {
	gin.SetMode(gin.TestMode)
	w := httptest.NewRecorder()
	_, r := gin.CreateTestContext(w)
	dir := t.TempDir()
	svc := account.New(dir)
	h := &AccountsHandler{Accounts: svc}
	g := r.Group("/api")
	h.Register(g)
	// create
	body, _ := json.Marshal(map[string]string{"email": "a@a.com", "token": "tok", "type": "Plus"})
	req, _ := http.NewRequest("POST", "/api/accounts", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("code %d", w.Code)
	}

	// batch import（RegiForge auto-import 与前端批量导入格式）
	batch, _ := json.Marshal(map[string]any{"accounts": []map[string]any{
		{"access_token": "tok-batch-1", "email": "b@a.com", "type": "free", "source_type": "web"},
		{"access_token": "tok-batch-2", "email": "c@a.com"},
	}, "tokens": []string{}})
	w = httptest.NewRecorder()
	req, _ = http.NewRequest("POST", "/api/accounts", bytes.NewReader(batch))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("batch code %d", w.Code)
	}
	var resp struct {
		Added   int   `json:"added"`
		Skipped int   `json:"skipped"`
		Errors  []any `json:"errors"`
	}
	_ = json.NewDecoder(w.Body).Decode(&resp)
	if resp.Added != 2 || resp.Skipped != 0 || len(resp.Errors) != 0 {
		t.Fatalf("batch resp %+v", resp)
	}
	if len(svc.List()) != 3 {
		t.Fatalf("accounts = %d, want 3", len(svc.List()))
	}

	// list
	w = httptest.NewRecorder()
	req, _ = http.NewRequest("GET", "/api/accounts", nil)
	r.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatal()
	}
}

// TB：导入透传 password/totp_secret/session_token，落盘保留但列表不回显明文。
func TestAdminAccountsImportRecoveryCreds(t *testing.T) {
	gin.SetMode(gin.TestMode)
	w := httptest.NewRecorder()
	_, r := gin.CreateTestContext(w)
	dir := t.TempDir()
	svc := account.New(dir)
	h := &AccountsHandler{Accounts: svc}
	g := r.Group("/api")
	h.Register(g)

	batch, _ := json.Marshal(map[string]any{"accounts": []map[string]any{
		{
			"access_token":  "tok-r1",
			"email":         "r@a.com",
			"type":          "free",
			"source_type":   "web",
			"password":      "Pw1!",
			"totp_secret":   "ABC123",
			"session_token": "sess-1",
		},
	}})
	w = httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/api/accounts", bytes.NewReader(batch))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("import code %d", w.Code)
	}

	// TB1：落盘保留恢复凭据
	var stored *account.Account
	for _, a := range svc.List() {
		if a.Token == "tok-r1" {
			stored = a
		}
	}
	if stored == nil {
		t.Fatal("imported account not found")
	}
	if stored.Password != "Pw1!" || stored.TOTPSecret != "ABC123" || stored.SessionToken != "sess-1" {
		t.Fatalf("creds not persisted: pw=%q totp=%q sess=%q", stored.Password, stored.TOTPSecret, stored.SessionToken)
	}
	// 重新加载（模拟重启）后仍在
	reloaded := account.New(dir)
	found := false
	for _, a := range reloaded.List() {
		if a.Token == "tok-r1" {
			found = true
			if a.Password != "Pw1!" || a.TOTPSecret != "ABC123" {
				t.Fatalf("creds lost after reload: %+v", a)
			}
		}
	}
	if !found {
		t.Fatal("account missing after reload")
	}

	// TB2：列表不回显明文密码/TOTP（只给 has_* / recoverable 布尔）
	w = httptest.NewRecorder()
	req, _ = http.NewRequest("GET", "/api/accounts", nil)
	r.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("list code %d", w.Code)
	}
	var listResp struct {
		Items []map[string]any `json:"items"`
	}
	_ = json.NewDecoder(w.Body).Decode(&listResp)
	var item map[string]any
	for _, it := range listResp.Items {
		if it["token"] == "tok-r1" {
			item = it
		}
	}
	if item == nil {
		t.Fatal("imported account not in list response")
	}
	if item["password"] != "" {
		t.Fatalf("password leaked in list: %v", item["password"])
	}
	if _, exists := item["totp_secret"]; exists {
		t.Fatalf("totp_secret present in list response: %v", item["totp_secret"])
	}
	if item["has_password"] != true || item["recoverable"] != true {
		t.Fatalf("has_password/recoverable wrong: %v / %v", item["has_password"], item["recoverable"])
	}
}

// TB3：不带恢复凭据导入 → 行为与改造前一致（回归），recoverable=false。
func TestAdminAccountsImportWithoutCreds(t *testing.T) {
	gin.SetMode(gin.TestMode)
	w := httptest.NewRecorder()
	_, r := gin.CreateTestContext(w)
	dir := t.TempDir()
	svc := account.New(dir)
	h := &AccountsHandler{Accounts: svc}
	g := r.Group("/api")
	h.Register(g)

	batch, _ := json.Marshal(map[string]any{"accounts": []map[string]any{
		{"access_token": "tok-plain", "email": "p@a.com", "type": "free", "source_type": "web"},
	}})
	w = httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/api/accounts", bytes.NewReader(batch))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("import code %d", w.Code)
	}
	for _, a := range svc.List() {
		if a.Token == "tok-plain" {
			if a.Password != "" || a.TOTPSecret != "" {
				t.Fatalf("unexpected creds: %+v", a)
			}
			return
		}
	}
	t.Fatal("imported account not found")
}

func TestSystem(t *testing.T) {
	gin.SetMode(gin.TestMode)
	w := httptest.NewRecorder()
	_, r := gin.CreateTestContext(w)
	cfg, _ := config.Load("")
	h := &SystemHandler{Cfg: cfg}
	g := r.Group("/api")
	h.Register(g)
	w = httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/api/config", nil)
	r.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatal()
	}
}
