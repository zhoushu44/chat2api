package api

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"chatgpt2api/internal/account"
	"chatgpt2api/internal/config"
	"chatgpt2api/internal/task"

	"github.com/gin-gonic/gin"
)

// TestImageTaskRoutesRegistered 图像创作页契约：路由必须存在（此前 404 导致额度读取失败/生图不可用）。
func TestImageTaskRoutesRegistered(t *testing.T) {
	gin.SetMode(gin.TestMode)
	cfg, _ := config.Load("")
	cfg.DataDir = t.TempDir()
	pool := account.NewPool(nil, 0)
	pool.Add(&account.Account{ID: "a1", Token: "t1", Status: account.StatusNormal, Quota: 5})
	taskSvc := task.New(t.TempDir())
	t.Cleanup(taskSvc.Close)
	taskSvc.Save(&task.Task{ID: "t-1", Status: task.Error, Model: "gpt-image-2"})
	s := &Server{
		Cfg:      cfg,
		Pool:     pool,
		Tasks:    taskSvc,
		Accounts: account.New(t.TempDir()),
	}
	r := s.NewRouter()

	for _, tc := range []struct {
		method, path string
	}{
		{"GET", "/api/image-tasks"},
		{"GET", "/api/image-tasks/quota"},
		{"POST", "/api/image-tasks/generations"},
		{"POST", "/api/image-tasks/edits"},
		{"POST", "/api/image-tasks/t-1/resume-poll"},
	} {
		req, _ := http.NewRequest(tc.method, tc.path, bytes.NewReader([]byte(`{"prompt":"cat"}`)))
		req.Header.Set("Content-Type", "application/json")
		w := httptest.NewRecorder()
		r.ServeHTTP(w, req)
		if w.Code == http.StatusNotFound {
			t.Errorf("%s %s got 404 (route not registered)", tc.method, tc.path)
		}
	}
}

// TestImageTaskQuotaShape 额度汇总字段必须齐备（前端 normalizeQuotaSummary 依赖）。
func TestImageTaskQuotaShape(t *testing.T) {
	gin.SetMode(gin.TestMode)
	cfg, _ := config.Load("")
	cfg.DataDir = t.TempDir()
	pool := account.NewPool(nil, 0)
	pool.Add(&account.Account{ID: "a1", Token: "t1", Status: account.StatusNormal, Quota: 5})
	pool.Add(&account.Account{ID: "a2", Token: "t2", Status: account.StatusNormal, Quota: -1})
	pool.Add(&account.Account{ID: "a3", Token: "t3", Status: account.StatusNormal, QuotaUnknown: true})
	taskSvc := task.New(t.TempDir())
	t.Cleanup(taskSvc.Close)
	s := &Server{Cfg: cfg, Pool: pool, Tasks: taskSvc}
	r := s.NewRouter()

	req, _ := http.NewRequest("GET", "/api/image-tasks/quota", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("got %d want 200 body=%s", w.Code, w.Body.String())
	}
	var got map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &got); err != nil {
		t.Fatalf("decode: %v", err)
	}
	for _, key := range []string{
		"total_quota", "unlimited_quota_count", "unknown_quota_count",
		"active_accounts", "limited_accounts", "abnormal_accounts", "disabled_accounts", "available",
	} {
		if _, ok := got[key]; !ok {
			t.Errorf("missing key %q in %v", key, got)
		}
	}
	if got["total_quota"].(float64) != 5 {
		t.Errorf("total_quota = %v want 5", got["total_quota"])
	}
	if got["unlimited_quota_count"].(float64) != 1 {
		t.Errorf("unlimited_quota_count = %v want 1", got["unlimited_quota_count"])
	}
	if got["unknown_quota_count"].(float64) != 1 {
		t.Errorf("unknown_quota_count = %v want 1", got["unknown_quota_count"])
	}
	if got["available"] != true {
		t.Errorf("available = %v want true", got["available"])
	}
}

// TestImageTaskListMissingIDs 悬挂 id 应回传 missing_ids 供前端清理。
func TestImageTaskListMissingIDs(t *testing.T) {
	gin.SetMode(gin.TestMode)
	cfg, _ := config.Load("")
	cfg.DataDir = t.TempDir()
	svc := task.New(t.TempDir())
	t.Cleanup(svc.Close)
	svc.Save(&task.Task{ID: "known", Status: task.Success, Model: "gpt-image-2"})
	s := &Server{Cfg: cfg, Tasks: svc}
	r := s.NewRouter()

	req, _ := http.NewRequest("GET", "/api/image-tasks?ids=known,ghost", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("got %d want 200", w.Code)
	}
	var got struct {
		Items      []map[string]any `json:"items"`
		MissingIDs []string         `json:"missing_ids"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &got); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(got.Items) != 1 || got.Items[0]["id"] != "known" {
		t.Errorf("items = %v want [known]", got.Items)
	}
	if len(got.MissingIDs) != 1 || got.MissingIDs[0] != "ghost" {
		t.Errorf("missing_ids = %v want [ghost]", got.MissingIDs)
	}
}
