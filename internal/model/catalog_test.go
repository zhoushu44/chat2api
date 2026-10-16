package model

import "testing"

// TestFallbackModels P1.4 验收：默认值与 Python FALLBACK_* 常量一致（gpt-5 系，无过时 gpt-4o/o1/o3）。
func TestFallbackModels(t *testing.T) {
	if len(FallbackChatModels) == 0 {
		t.Fatal("empty fallback chat models")
	}
	want := map[string]bool{"auto": true, "gpt-5": true, "gpt-5-mini": true, "gpt-5-3": true}
	for _, m := range FallbackChatModels {
		delete(want, m)
	}
	for m := range want {
		t.Fatalf("fallback chat models missing %q", m)
	}
	for _, m := range FallbackChatModels {
		if m == "gpt-4o" || m == "o1" || m == "o3" {
			t.Fatalf("stale model in fallback: %q", m)
		}
	}
	if len(FallbackImageModels) != 1 || FallbackImageModels[0] != "gpt-image-2" {
		t.Fatalf("fallback image models=%v", FallbackImageModels)
	}
}

// TestDeriveFromAccounts P1.4：账号派生 codex 模型与 plan 前缀变体。
func TestDeriveFromAccounts(t *testing.T) {
	c := New()
	c.DeriveFromAccounts(map[string]int{"plus": 2}, true)
	snap := c.Snapshot()
	if snap["image_source"] != "accounts" {
		t.Fatalf("source=%v", snap["image_source"])
	}
	images, _ := snap["image_models"].([]string)
	has := func(v string) bool {
		for _, m := range images {
			if m == v {
				return true
			}
		}
		return false
	}
	if !has("gpt-image-2") || !has("codex-gpt-image-2") || !has("plus-codex-gpt-image-2") {
		t.Fatalf("derived image models incomplete: %v", images)
	}
}

// TestSetConfigured P1.4：显式配置覆盖。
func TestSetConfigured(t *testing.T) {
	c := New()
	c.SetConfigured([]string{"gpt-5", "gpt-5"}, []string{"gpt-image-2"})
	if c.Source != "config" {
		t.Fatalf("source=%q", c.Source)
	}
	if len(c.ChatModels) != 1 || c.ChatModels[0] != "gpt-5" {
		t.Fatalf("dedupe failed: %v", c.ChatModels)
	}
}

// TestAddChatNoDup P1.4：AddChat 去重（原实现无限追加）。
func TestAddChatNoDup(t *testing.T) {
	c := New()
	n := len(c.ChatModels)
	c.AddChat("gpt-5")
	if len(c.ChatModels) != n {
		t.Fatalf("duplicate add appended: %d -> %d", n, len(c.ChatModels))
	}
	c.AddChat("gpt-5-custom")
	if len(c.ChatModels) != n+1 {
		t.Fatalf("new add missing: %d", len(c.ChatModels))
	}
}
