package config

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

// TestNewKeysDefaults P2.7：新增段默认值与 Python example 一致。
func TestNewKeysDefaults(t *testing.T) {
	cfg := defaults()
	if cfg.RefreshAccountMin != 5 || cfg.ImageRetentionDays != 15 || cfg.LogRetentionDays != 30 {
		t.Fatalf("retention defaults: %+v", cfg)
	}
	if cfg.ImageMinFreeMB != 500 {
		t.Fatalf("min free mb=%d", cfg.ImageMinFreeMB)
	}
	if cfg.ProxyRuntime.EgressMode != "direct" {
		t.Fatalf("egress=%q", cfg.ProxyRuntime.EgressMode)
	}
	if cfg.ImageStorage.Mode != "local" || cfg.ImageStorage.WebDAVRoot != "chatgpt2api/images" {
		t.Fatalf("storage=%+v", cfg.ImageStorage)
	}
	if !cfg.ChatCompletionCache.DropAdjacentDuplicates || cfg.ChatCompletionCache.DropAssistantHistory {
		t.Fatalf("cache=%+v", cfg.ChatCompletionCache)
	}
	if !cfg.ImageGeneration.Enabled {
		t.Fatal("image generation should default enabled")
	}
	if cfg.QuotaLimits.FastDailyLimit != -1 || cfg.QuotaLimits.ImageDailyLimit != -1 {
		t.Fatalf("quota=%+v", cfg.QuotaLimits)
	}
	if cfg.Clearance.Mode != "none" || cfg.Clearance.TimeoutSec != 60 {
		t.Fatalf("clearance=%+v", cfg.Clearance)
	}
}

// TestNewKeysLoad P2.7：JSON 加载新增键。
func TestNewKeysLoad(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "config.json")
	raw := `{
		"proxy": "http://127.0.0.1:8080",
		"sensitive_words": ["foo", "bar"],
		"global_system_prompt": "be nice",
		"proxy_runtime": {"enabled": true, "proxy_url": "http://127.0.0.1:9090"},
		"image_storage": {"enabled": true, "mode": "webdav", "webdav_url": "https://dav.example.com/", "webdav_username": "u"},
		"ai_review": {"enabled": true, "model": "m"},
		"image_generation": {"enabled": false},
		"quota_limits": {"enabled": true, "image_daily_limit": 10}
	}`
	if err := os.WriteFile(path, []byte(raw), 0644); err != nil {
		t.Fatal(err)
	}
	cfg, err := Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Proxy != "http://127.0.0.1:8080" {
		t.Fatalf("proxy=%q", cfg.Proxy)
	}
	if len(cfg.SensitiveWords) != 2 {
		t.Fatalf("sensitive=%v", cfg.SensitiveWords)
	}
	if cfg.GlobalSystemPrompt != "be nice" {
		t.Fatalf("sysprompt=%q", cfg.GlobalSystemPrompt)
	}
	if !cfg.ProxyRuntime.Enabled || cfg.ProxyRuntime.ProxyURL != "http://127.0.0.1:9090" {
		t.Fatalf("runtime=%+v", cfg.ProxyRuntime)
	}
	if cfg.EffectiveProxy() != "http://127.0.0.1:9090" {
		t.Fatalf("effective=%q", cfg.EffectiveProxy())
	}
	if cfg.ImageStorage.Mode != "webdav" || cfg.ImageStorage.WebDAVUser != "u" {
		t.Fatalf("storage=%+v", cfg.ImageStorage)
	}
	if !cfg.AIReview.Enabled || cfg.AIReview.Model != "m" {
		t.Fatalf("aireview=%+v", cfg.AIReview)
	}
	if cfg.ImageGeneration.Enabled {
		t.Fatal("image_generation.enabled=false not loaded")
	}
	if cfg.QuotaLimits.ImageDailyLimit != 10 {
		t.Fatalf("quota=%+v", cfg.QuotaLimits)
	}
	// 未指定的键保持默认
	if cfg.ImageRetentionDays != 15 {
		t.Fatalf("default lost: %d", cfg.ImageRetentionDays)
	}
}

// TestEffectiveProxyFallback P2.7：runtime 未启用时回退顶层 proxy。
func TestEffectiveProxyFallback(t *testing.T) {
	cfg := defaults()
	cfg.Proxy = "http://top:8080"
	if cfg.EffectiveProxy() != "http://top:8080" {
		t.Fatalf("fallback=%q", cfg.EffectiveProxy())
	}
	var nilCfg *Config
	if nilCfg.EffectiveProxy() != "" {
		t.Fatal("nil config should be empty")
	}
}

// TestImageGenGateSemantics P2.7：门控只对显式禁用生效。
func TestImageGenGateSemantics(t *testing.T) {
	// 零值 Config（字面量构造）→ 视为启用
	var zero Config
	if zero.ImageGeneration.ExplicitlyDisabled() {
		t.Fatal("zero config should not disable")
	}
	// 未出现该段的 JSON → 启用
	var absent struct {
		Gen ImageGenerationConfig `json:"image_generation"`
	}
	if err := json.Unmarshal([]byte(`{}`), &absent); err != nil {
		t.Fatal(err)
	}
	// 注意：段落缺席时 UnmarshalJSON 不会被调用
	if absent.Gen.ExplicitlyDisabled() {
		t.Fatal("absent section should not disable")
	}
	// 显式 false → 禁用
	var off struct {
		Gen ImageGenerationConfig `json:"image_generation"`
	}
	if err := json.Unmarshal([]byte(`{"image_generation":{"enabled":false}}`), &off); err != nil {
		t.Fatal(err)
	}
	if !off.Gen.ExplicitlyDisabled() {
		t.Fatal("explicit false should disable")
	}
	// 显式 true → 启用
	var on struct {
		Gen ImageGenerationConfig `json:"image_generation"`
	}
	if err := json.Unmarshal([]byte(`{"image_generation":{"enabled":true}}`), &on); err != nil {
		t.Fatal(err)
	}
	if on.Gen.ExplicitlyDisabled() {
		t.Fatal("explicit true should not disable")
	}
	// nil 接收者安全
	var nilGen *ImageGenerationConfig
	if nilGen.ExplicitlyDisabled() {
		t.Fatal("nil should not disable")
	}
}
func TestConfigRoundtripJSON(t *testing.T) {
	b, err := json.Marshal(defaults())
	if err != nil {
		t.Fatal(err)
	}
	var m map[string]any
	if err := json.Unmarshal(b, &m); err != nil {
		t.Fatal(err)
	}
	for _, key := range []string{"proxy_runtime", "image_storage", "chat_completion_cache", "ai_review", "backup", "image_generation", "quota_limits", "sensitive_words", "global_system_prompt"} {
		if _, ok := m[key]; !ok {
			t.Fatalf("missing key %q in serialized config", key)
		}
	}
}
