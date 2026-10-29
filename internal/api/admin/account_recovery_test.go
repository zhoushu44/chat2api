package admin

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"chatgpt2api/internal/account"

	"github.com/gin-gonic/gin"
)

// 注册导出器透传恢复凭据：Go 必须持久化，但列表接口不得回显明文。
func TestAccountsImportRecoveryCredentialsAndMaskList(t *testing.T) {
	gin.SetMode(gin.TestMode)
	dir := t.TempDir()
	svc := account.New(dir)
	pool := account.NewPool(nil, 0)
	h := &AccountsHandler{Accounts: svc, Pool: pool}
	_, router := gin.CreateTestContext(httptest.NewRecorder())
	h.Register(router.Group("/api"))

	payload := map[string]any{
		"id": "recover@e.com", "token": "AT-secret", "email": "recover@e.com",
		"type": "free", "source_type": "web", "status": "正常",
		"password": "pw-secret", "totp_secret": "totp-secret", "session_token": "session-secret",
	}
	body, _ := json.Marshal(payload)
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/api/accounts", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("import code=%d body=%s", w.Code, w.Body.String())
	}

	// 池内与持久化都必须有恢复凭据
	if got := pool.List(); len(got) != 1 || got[0].Password != "pw-secret" || got[0].TOTPSecret != "totp-secret" || got[0].SessionToken != "session-secret" {
		t.Fatalf("pool credentials missing: %+v", got)
	}
	persisted, ok := account.New(dir).Get("recover@e.com")
	if !ok || persisted.Password != "pw-secret" || persisted.TOTPSecret != "totp-secret" || persisted.SessionToken != "session-secret" {
		t.Fatalf("persisted credentials missing: %+v ok=%v", persisted, ok)
	}

	// 列表只能返回 recoverable/has_*，不能泄露任何明文凭据
	w = httptest.NewRecorder()
	req, _ = http.NewRequest("GET", "/api/accounts", nil)
	router.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("list code=%d", w.Code)
	}
	text := w.Body.String()
	for _, secret := range []string{"pw-secret", "totp-secret", "session-secret"} {
		if bytes.Contains([]byte(text), []byte(secret)) {
			t.Fatalf("list leaked secret %q: %s", secret, text)
		}
	}
	var response struct {
		Items []map[string]any `json:"items"`
	}
	if err := json.Unmarshal([]byte(text), &response); err != nil || len(response.Items) != 1 {
		t.Fatalf("list decode: %v %s", err, text)
	}
	item := response.Items[0]
	if item["recoverable"] != true || item["has_password"] != true || item["has_totp"] != true {
		t.Fatalf("recovery flags missing: %+v", item)
	}
	if item["password"] != "" {
		t.Fatalf("password should be masked: %+v", item)
	}
}
