package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"chatgpt2api/internal/account"

	"github.com/gin-gonic/gin"
)

func TestAccountsStats(t *testing.T) {
	gin.SetMode(gin.TestMode)
	dir := t.TempDir()
	svc := account.New(dir)

	now := time.Now().Unix()
	// 2 个活号（其中一个有产出 + 恢复过），1 个死号
	svc.Add(&account.Account{ID: "a1", Token: "t1", Email: "a1@x", Status: account.StatusNormal,
		Quota: 25, CreatedAt: now - 3600, ImagesOK: 10, ReviveCount: 1})
	svc.Add(&account.Account{ID: "a2", Token: "t2", Email: "a2@x", Status: account.StatusNormal,
		Quota: 25, CreatedAt: now - 7200, ImagesOK: 5})
	svc.Add(&account.Account{ID: "a3", Token: "t3", Email: "a3@x", Status: account.StatusDisabled,
		Quota: 0, CreatedAt: now - 86400, DiedAt: now - 3600, DeathReason: "token_revoked", ImagesOK: 20})

	h := &AccountsStatsHandler{Accounts: svc}
	_, r := gin.CreateTestContext(httptest.NewRecorder())
	h.Register(r.Group("/api"))

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/api/stats/accounts", nil)
	r.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("code=%d body=%s", w.Code, w.Body.String())
	}
	var body struct {
		Output map[string]any `json:"output"`
		Life   map[string]any `json:"life"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
		t.Fatalf("bad json: %v", err)
	}
	if body.Output["total_images_ok"].(float64) != 35 {
		t.Fatalf("total_images_ok=%v", body.Output["total_images_ok"])
	}
	if body.Output["total_revive"].(float64) != 1 {
		t.Fatalf("total_revive=%v", body.Output["total_revive"])
	}
	if body.Life["alive"].(float64) != 2 || body.Life["dead"].(float64) != 1 {
		t.Fatalf("life=%v", body.Life)
	}
	if body.Life["avg_lifetime_h"].(float64) <= 0 {
		t.Fatalf("avg_lifetime_h should be > 0, got %v", body.Life["avg_lifetime_h"])
	}
	reason := body.Life["death_reason"].(map[string]any)
	if reason["token_revoked"].(float64) != 1 {
		t.Fatalf("death_reason=%v", reason)
	}
}
