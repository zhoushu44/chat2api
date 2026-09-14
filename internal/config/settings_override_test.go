package config

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

// 端到端：settings.json 里的值必须真的合并进 config.Get()，而不只是躺在磁盘上。
// 这是「保存后不生效」缺陷的回归防线。
func TestSettingsFileOverridesConfig(t *testing.T) {
	dir := t.TempDir()
	stored := map[string]any{
		"base_url":                        "https://override.example",
		"image_retention_days":            7,
		"refresh_account_interval_minute": 11,
		"sensitive_words":                 []string{"alpha", "beta"},
		"global_system_prompt":            "OVERRIDE-PROMPT",
		"proxy":                           "http://override-proxy:8080",
		"image_generation": map[string]any{
			"enabled":       false,
			"output_format": "url",
		},
	}
	raw, _ := json.Marshal(stored)
	if err := os.WriteFile(filepath.Join(dir, "settings.json"), raw, 0o644); err != nil {
		t.Fatal(err)
	}

	cfg, err := Load("")
	if err != nil {
		t.Fatal(err)
	}
	cfg.DataDir = dir
	EnableOverridesFromDir(dir)

	got := Get()
	if got.BaseURL != "https://override.example" {
		t.Errorf("BaseURL=%q", got.BaseURL)
	}
	if got.ImageRetentionDays != 7 {
		t.Errorf("ImageRetentionDays=%d", got.ImageRetentionDays)
	}
	if got.RefreshAccountMin != 11 {
		t.Errorf("RefreshAccountMin=%d", got.RefreshAccountMin)
	}
	if len(got.SensitiveWords) != 2 || got.SensitiveWords[0] != "alpha" {
		t.Errorf("SensitiveWords=%v", got.SensitiveWords)
	}
	if got.GlobalSystemPrompt != "OVERRIDE-PROMPT" {
		t.Errorf("GlobalSystemPrompt=%q", got.GlobalSystemPrompt)
	}
	if got.EffectiveProxy() != "http://override-proxy:8080" {
		t.Errorf("EffectiveProxy=%q", got.EffectiveProxy())
	}
	// 面板显式关闭生图，门控必须真的生效
	if !got.ImageGeneration.ExplicitlyDisabled() {
		t.Error("image_generation.enabled=false should disable generation")
	}
	if got.ImageGeneration.OutputFormat != "url" {
		t.Errorf("OutputFormat=%q", got.ImageGeneration.OutputFormat)
	}

	// 凭证类键不允许从面板回写（防止面板保存把部署密钥冲空）
	if got.AuthKey != "" {
		t.Errorf("AuthKey must not be overridden by settings.json, got %q", got.AuthKey)
	}
}

// 没有 settings.json 时不得影响默认配置。
func TestNoSettingsFileKeepsDefaults(t *testing.T) {
	dir := t.TempDir()
	if _, err := Load(""); err != nil {
		t.Fatal(err)
	}
	before := *Get()
	EnableOverridesFromDir(dir)
	after := *Get()
	if before.BaseURL != after.BaseURL || before.ImageRetentionDays != after.ImageRetentionDays {
		t.Fatal("empty settings dir must not change config")
	}
}

// ApplyRuntime 热更新代理与敏感词。
func TestApplyRuntimeHotUpdate(t *testing.T) {
	if _, err := Load(""); err != nil {
		t.Fatal(err)
	}
	ApplyRuntime(map[string]any{
		"proxy":           "http://hot-proxy:3128",
		"sensitive_words": []string{"hotword"},
		"proxy_runtime": map[string]any{
			"enabled":    true,
			"egress_mode": "single_proxy",
			"proxy_url":  "http://hot-proxy:3128",
		},
	})
	got := Get()
	if got.Proxy != "http://hot-proxy:3128" {
		t.Errorf("Proxy=%q", got.Proxy)
	}
	if len(got.SensitiveWords) != 1 || got.SensitiveWords[0] != "hotword" {
		t.Errorf("SensitiveWords=%v", got.SensitiveWords)
	}
	if !got.ProxyRuntime.Enabled || got.ProxyRuntime.EgressMode != "single_proxy" {
		t.Errorf("ProxyRuntime=%+v", got.ProxyRuntime)
	}
}

// clearance 留空表示沿用，不能把已保存的 cookie 清空。
func TestApplyRuntimeKeepsBlankSecrets(t *testing.T) {
	if _, err := Load(""); err != nil {
		t.Fatal(err)
	}
	cfg := Get()
	cfg.Clearance.CfCookies = "saved-cookie"
	cfg.Clearance.CfClearance = "saved-clearance"

	ApplyRuntime(map[string]any{"clearance": map[string]any{
		"enabled":      true,
		"cf_cookies":   "",
		"cf_clearance": "  ",
	}})
	got := Get()
	if got.Clearance.CfCookies != "saved-cookie" {
		t.Errorf("blank cf_cookies must not clear saved value, got %q", got.Clearance.CfCookies)
	}
	if got.Clearance.CfClearance != "saved-clearance" {
		t.Errorf("blank cf_clearance must not clear saved value, got %q", got.Clearance.CfClearance)
	}
	if !got.Clearance.Enabled {
		t.Error("clearance.enabled should be applied")
	}
}
