package filter

import (
	"testing"

	"chatgpt2api/internal/config"
	"chatgpt2api/internal/image"
)

// TestCustomWords P2.7：配置 sensitive_words 生效（与内置合并）。
func TestCustomWords(t *testing.T) {
	SetCustomWords([]string{"foo", "BAR"})
	defer SetCustomWords(nil)
	if ok, _ := IsAllowed("this has foo inside"); ok {
		t.Fatal("custom word foo not blocked")
	}
	if ok, _ := IsAllowed("BAR baz"); ok {
		t.Fatal("custom word BAR not blocked (case-insensitive)")
	}
	if ok, _ := IsAllowed("clean prompt"); !ok {
		t.Fatal("clean prompt blocked")
	}
	// 内置仍有效
	if ok, _ := IsAllowed("nsfw content"); ok {
		t.Fatal("builtin word lost")
	}
}

// TestStorageSelector P2.7：image_storage 配置选择存储后端。
func TestStorageSelector(t *testing.T) {
	dir := t.TempDir()
	// 默认 local
	s := image.StorageFromConfig(dir, nil)
	if _, ok := s.(*image.LocalStorage); !ok {
		t.Fatalf("nil cfg -> %T", s)
	}
	// webdav 模式
	cfg := &config.ImageStorageConfig{Enabled: true, Mode: "webdav", WebDAVURL: "https://dav.example.com/", WebDAVRoot: "r"}
	s2 := image.StorageFromConfig(dir, cfg)
	if _, ok := s2.(*image.WebDAVStorage); !ok {
		t.Fatalf("webdav cfg -> %T", s2)
	}
	// both 模式带本地
	cfg.Mode = "both"
	s3 := image.StorageFromConfig(dir, cfg)
	ws, ok := s3.(*image.WebDAVStorage)
	if !ok {
		t.Fatalf("both cfg -> %T", s3)
	}
	if ws.Test().OK {
		t.Fatal("unreachable webdav should fail test")
	}
}
