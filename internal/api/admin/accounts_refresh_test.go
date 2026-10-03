package admin

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"chatgpt2api/internal/account"
	"chatgpt2api/internal/backend"
	"chatgpt2api/internal/refresh"

	"github.com/gin-gonic/gin"
)

// waitForRefreshDone 轮询等待刷新完成。
func waitForRefreshDone(t *testing.T, id string, timeout time.Duration) *refresh.Progress {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if p := refresh.GetProgress(id); p != nil && p.Done {
			return p
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("refresh %s not done within %v", id, timeout)
	return nil
}

// TA-R1：POST /accounts/refresh 启动 + GET progress 轮询直到 done（前端 refreshAndPoll 契约）。
func TestAccountsRefreshRouteContract(t *testing.T) {
	gin.SetMode(gin.TestMode)
	w := httptest.NewRecorder()
	_, r := gin.CreateTestContext(w)
	dir := t.TempDir()
	svc := account.New(dir)
	_ = svc.Add(&account.Account{Token: "tok-1", Email: "a@a.com", Status: account.StatusNormal})
	pool := account.NewPool(nil, 0)
	for _, a := range svc.List() {
		pool.Add(a)
	}
	ref := &refresh.Service{
		Accounts: svc,
		Pool:     pool,
		Probe: func(ctx context.Context, a *account.Account) (backend.AccountQuota, error) {
			return backend.AccountQuota{OK: true, Quota: 25}, nil
		},
	}
	h := &AccountsHandler{Accounts: svc, Pool: pool, Refresh: ref}
	g := r.Group("/api")
	h.Register(g)

	// 启动
	body, _ := json.Marshal(map[string]any{"access_tokens": []string{"tok-1"}})
	req, _ := http.NewRequest("POST", "/api/accounts/refresh", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w = httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("start code %d body=%s", w.Code, w.Body.String())
	}
	var start struct {
		ProgressID string `json:"progress_id"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &start); err != nil {
		t.Fatalf("decode start: %v", err)
	}
	if start.ProgressID == "" {
		t.Fatal("progress_id empty")
	}

	// 轮询到 done
	p := waitForRefreshDone(t, start.ProgressID, 5*time.Second)
	if p.Refreshed != 1 {
		t.Fatalf("Refreshed = %d want 1", p.Refreshed)
	}

	// GET progress：done + result 形状
	req2, _ := http.NewRequest("GET", "/api/accounts/refresh/progress/"+start.ProgressID, nil)
	w2 := httptest.NewRecorder()
	r.ServeHTTP(w2, req2)
	if w2.Code != 200 {
		t.Fatalf("progress code %d", w2.Code)
	}
	var prog map[string]any
	if err := json.Unmarshal(w2.Body.Bytes(), &prog); err != nil {
		t.Fatalf("decode progress: %v", err)
	}
	if prog["done"] != true {
		t.Errorf("done = %v", prog["done"])
	}
	if _, ok := prog["result"]; !ok {
		t.Errorf("result key missing: %v", prog)
	}
	result := prog["result"].(map[string]any)
	if result["refreshed"].(float64) != 1 {
		t.Errorf("result.refreshed = %v", result["refreshed"])
	}

	// 额度已回写
	for _, a := range pool.List() {
		if a.Quota != 25 {
			t.Errorf("pool quota = %d want 25", a.Quota)
		}
	}
}

// TA-R2：空 body → 全量刷新（不是 400）。
func TestAccountsRefreshEmptyBody(t *testing.T) {
	gin.SetMode(gin.TestMode)
	w := httptest.NewRecorder()
	_, r := gin.CreateTestContext(w)
	dir := t.TempDir()
	svc := account.New(dir)
	_ = svc.Add(&account.Account{Token: "tok-1", Email: "a@a.com", Status: account.StatusNormal})
	pool := account.NewPool(nil, 0)
	for _, a := range svc.List() {
		pool.Add(a)
	}
	ref := &refresh.Service{
		Accounts: svc,
		Pool:     pool,
		Probe: func(ctx context.Context, a *account.Account) (backend.AccountQuota, error) {
			return backend.AccountQuota{OK: true, Quota: 5}, nil
		},
	}
	h := &AccountsHandler{Accounts: svc, Pool: pool, Refresh: ref}
	g := r.Group("/api")
	h.Register(g)

	req, _ := http.NewRequest("POST", "/api/accounts/refresh", nil)
	w = httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("empty body code %d body=%s", w.Code, w.Body.String())
	}
	var start struct {
		ProgressID string `json:"progress_id"`
	}
	_ = json.Unmarshal(w.Body.Bytes(), &start)
	if start.ProgressID == "" {
		t.Fatal("progress_id empty")
	}
	waitForRefreshDone(t, start.ProgressID, 5*time.Second)
}

// TA-R3：未知 progress id → done:true（前端据此停止轮询）。
func TestAccountsRefreshProgressUnknown(t *testing.T) {
	gin.SetMode(gin.TestMode)
	w := httptest.NewRecorder()
	_, r := gin.CreateTestContext(w)
	h := &AccountsHandler{Accounts: account.New(t.TempDir())}
	g := r.Group("/api")
	h.Register(g)

	req, _ := http.NewRequest("GET", "/api/accounts/refresh/progress/ghost", nil)
	w = httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("code %d", w.Code)
	}
	var prog map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &prog)
	if prog["done"] != true {
		t.Errorf("done = %v want true", prog["done"])
	}
}

// TA-R4：Refresh 未注入 → 503（不 panic）。
func TestAccountsRefreshServiceUnavailable(t *testing.T) {
	gin.SetMode(gin.TestMode)
	w := httptest.NewRecorder()
	_, r := gin.CreateTestContext(w)
	h := &AccountsHandler{Accounts: account.New(t.TempDir())}
	g := r.Group("/api")
	h.Register(g)

	req, _ := http.NewRequest("POST", "/api/accounts/refresh", nil)
	w = httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code != 503 {
		t.Fatalf("code %d want 503", w.Code)
	}
}
