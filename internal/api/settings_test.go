package api

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"chatgpt2api/internal/config"
	"chatgpt2api/internal/settings"

	"github.com/gin-gonic/gin"
)

func newSettingsTestRouter(t *testing.T) (*gin.Engine, string) {
	t.Helper()
	gin.SetMode(gin.TestMode)
	dir := t.TempDir()
	// config.Load 会写入全局配置（globalConfig），必须在这里调用，
	// 否则 config.Get()/ApplyRuntime 读到的是另一份实例。
	cfg, err := config.Load("")
	if err != nil {
		t.Fatalf("load config: %v", err)
	}
	cfg.DataDir = dir
	cfg.SensitiveWords = nil
	s := &Server{Cfg: cfg}
	return s.NewRouter(), dir
}

// 复现原始缺陷：面板保存必须真正落盘，刷新后 GET 能读回。
func TestSettingsSavePersistsAndReadsBack(t *testing.T) {
	r, dir := newSettingsTestRouter(t)

	payload := map[string]any{
		"base_url":               "https://img.example.com",
		"image_retention_days":   7,
		"image_account_concurrency": 5,
		"sensitive_words":        []string{"foo", "bar"},
		"third_party_apps": map[string]any{
			"infinite_canvas": map[string]any{"enabled": true, "url": "https://canvas.example"},
		},
	}
	body, _ := json.Marshal(payload)
	req, _ := http.NewRequest("POST", "/api/settings", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("save got %d body=%s", w.Code, w.Body.String())
	}

	// 必须真的写进 settings.json
	stored := settings.NewStore(dir).Snapshot()
	if stored["base_url"] != "https://img.example.com" {
		t.Fatalf("base_url not persisted: %v", stored["base_url"])
	}
	if stored["image_retention_days"] != float64(7) {
		t.Fatalf("image_retention_days not persisted: %v", stored["image_retention_days"])
	}

	// GET 必须回读同一份
	reqGet, _ := http.NewRequest("GET", "/api/settings", nil)
	wGet := httptest.NewRecorder()
	r.ServeHTTP(wGet, reqGet)
	if wGet.Code != http.StatusOK {
		t.Fatalf("get got %d", wGet.Code)
	}
	var resp struct {
		Config map[string]any `json:"config"`
	}
	if err := json.Unmarshal(wGet.Body.Bytes(), &resp); err != nil {
		t.Fatalf("decode get: %v", err)
	}
	if resp.Config["base_url"] != "https://img.example.com" {
		t.Fatalf("get did not return saved value: %v", resp.Config["base_url"])
	}
}

// GET 在无 settings.json 时必须返回配置播种值，而不是空对象
// （否则前端 normalizeSettings 会把表单回填成全默认值）。
func TestSettingsGetSeedsFromConfig(t *testing.T) {
	r, _ := newSettingsTestRouter(t)
	req, _ := http.NewRequest("GET", "/api/settings", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("got %d", w.Code)
	}
	var resp struct {
		Config map[string]any `json:"config"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatal(err)
	}
	if len(resp.Config) == 0 {
		t.Fatal("expected seeded settings, got empty object")
	}
	if _, ok := resp.Config["image_retention_days"]; !ok {
		t.Fatalf("seed missing image_retention_days: %v", resp.Config)
	}
}

// 未注册的 /api/* 必须 404，不能被 SPA fallback 吞成 200 index.html。
func TestUnknownAPIRouteReturns404NotIndexHTML(t *testing.T) {
	r, _ := newSettingsTestRouter(t)
	for _, path := range []string{"/api/not-a-real-endpoint", "/v1/not-a-real-endpoint"} {
		req, _ := http.NewRequest("POST", path, bytes.NewReader([]byte("{}")))
		req.Header.Set("Content-Type", "application/json")
		w := httptest.NewRecorder()
		r.ServeHTTP(w, req)
		if w.Code != http.StatusNotFound {
			t.Errorf("%s got %d want 404 body=%s", path, w.Code, truncate(w.Body.String()))
		}
		if bytes.Contains(w.Body.Bytes(), []byte("<!doctype html")) {
			t.Errorf("%s returned SPA index.html instead of JSON error", path)
		}
	}
}

// 页面路由仍要能走 SPA fallback。
func TestPageRouteStillServesSPA(t *testing.T) {
	r, _ := newSettingsTestRouter(t)
	req, _ := http.NewRequest("GET", "/settings", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code == http.StatusNotFound {
		t.Fatalf("page route should fall back to SPA, got 404")
	}
}

// 保存非法 JSON 要明确报错，而不是静默成功。
func TestSettingsSaveRejectsInvalidJSON(t *testing.T) {
	r, dir := newSettingsTestRouter(t)
	req, _ := http.NewRequest("POST", "/api/settings", bytes.NewReader([]byte(`{not json`)))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("got %d want 400 body=%s", w.Code, truncate(w.Body.String()))
	}
	if len(settings.NewStore(dir).Snapshot()) != 0 {
		t.Fatal("invalid payload must not be persisted")
	}
}

// 面板保存的敏感词要即时生效（热应用，不必重启）。
func TestSettingsSaveAppliesSensitiveWordsImmediately(t *testing.T) {
	r, _ := newSettingsTestRouter(t)
	body, _ := json.Marshal(map[string]any{"sensitive_words": []string{"zzz-hot-reload-word"}})
	req, _ := http.NewRequest("POST", "/api/settings", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("save got %d", w.Code)
	}
	if cfg := config.Get(); len(cfg.SensitiveWords) != 1 || cfg.SensitiveWords[0] != "zzz-hot-reload-word" {
		t.Fatalf("sensitive words not hot-applied: %v body=%s", cfg.SensitiveWords, w.Body.String())
	}
}

// 面板保存后，重启（重新 Load）也必须读到面板值。
func TestSavedSettingsSurviveConfigReload(t *testing.T) {
	r, dir := newSettingsTestRouter(t)
	body, _ := json.Marshal(map[string]any{"base_url": "https://persisted.example", "image_retention_days": 3})
	req, _ := http.NewRequest("POST", "/api/settings", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("save got %d", w.Code)
	}

	reloaded, err := config.Load("")
	if err != nil {
		t.Fatal(err)
	}
	config.EnableOverridesFromDir(dir)
	cfg := config.Get()
	if cfg.BaseURL != "https://persisted.example" {
		t.Fatalf("base_url not reloaded: %q", cfg.BaseURL)
	}
	if cfg.ImageRetentionDays != 3 {
		t.Fatalf("image_retention_days not reloaded: %d", cfg.ImageRetentionDays)
	}
	_ = reloaded
}

func truncate(s string) string {
	if len(s) > 300 {
		return s[:300]
	}
	return s
}
