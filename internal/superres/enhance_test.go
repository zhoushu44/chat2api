package superres

import (
	"context"
	"encoding/base64"
	"testing"
	"time"
)

// TestShouldEnhanceGate 开关与尺寸门槛。
func TestShouldEnhanceGate(t *testing.T) {
	readyCfg := &Config{
		Enabled:       true,
		SecretID:      "id",
		SecretKey:     "key",
		Bucket:        "b-1250000000",
		Region:        "ap-guangzhou",
		PublicBaseURL: "https://b-1250000000.cos.ap-guangzhou.myqcloud.com",
	}
	// 未配置 / 关闭 → 不接管
	if ShouldEnhance(nil, "2k") != nil {
		t.Fatal("nil config should not enhance")
	}
	offCfg := *readyCfg
	offCfg.Enabled = false
	if ShouldEnhance(&offCfg, "2k") != nil {
		t.Fatal("disabled config should not enhance")
	}
	partialCfg := *readyCfg
	partialCfg.SecretKey = ""
	if ShouldEnhance(&partialCfg, "2k") != nil {
		t.Fatal("missing credentials should not enhance")
	}
	// 1k / auto / 未带尺寸 → 不接管（factor=1）
	for _, size := range []string{"", "auto", "1k", "1024x704"} {
		if p := ShouldEnhance(readyCfg, size); p != nil {
			t.Fatalf("size %q should not enhance, got plan %+v", size, p)
		}
	}
	// 2k / 4k / 自定义大尺寸 → 接管
	for _, size := range []string{"2k", "4k", "2048x1024", "2560x1440"} {
		p := ShouldEnhance(readyCfg, size)
		if p == nil {
			t.Fatalf("size %q should enhance, got nil", size)
		}
		if p.Factor != 2 && p.Factor != 4 {
			t.Fatalf("size %q factor = %d, want 2 or 4", size, p.Factor)
		}
	}
	// 非法尺寸 → 不接管不报错（沿用原链路行为）
	if p := ShouldEnhance(readyCfg, "999x333"); p != nil {
		t.Fatalf("invalid size should not enhance, got %+v", p)
	}
}

// TestSplitDataURL dataURL 解析。
func TestSplitDataURL(t *testing.T) {
	// 合法 PNG data URL
	png := "data:image/png;base64," + base64.StdEncoding.EncodeToString([]byte{0x89, 0x50, 0x4E, 0x47})
	ct, data, ok := splitDataURL(png)
	if !ok || ct != "image/png" || len(data) != 4 {
		t.Fatalf("splitDataURL(png) = %q,%d,%v", ct, len(data), ok)
	}
	// 无 mediatype 默认 png
	bare := "data:;base64," + base64.StdEncoding.EncodeToString([]byte("xx"))
	ct, _, ok = splitDataURL(bare)
	if !ok || ct != "image/png" {
		t.Fatalf("splitDataURL(bare) = %q,%v", ct, ok)
	}
	// 非 dataURL / 非 base64 / 坏 base64
	for _, bad := range []string{
		"https://example.com/a.png",
		"data:image/png,not-base64-payload",
		"data:image/png;base64,!!!!",
		"data:image/png;base64,",
	} {
		if _, _, ok := splitDataURL(bad); ok {
			t.Fatalf("splitDataURL(%q) should fail", bad)
		}
	}
}

// TestEnhanceFallback 失败降级：坏配置（不可达 bucket）时返回原图，不 panic。
func TestEnhanceFallback(t *testing.T) {
	cfg := &Config{
		Enabled:       true,
		SecretID:      "id",
		SecretKey:     "key",
		Bucket:        "no-such-bucket-0000000000",
		Region:        "ap-guangzhou",
		PublicBaseURL: "https://no-such-bucket-0000000000.cos.ap-guangzhou.myqcloud.com",
	}
	plan, err := PlanSize("2k")
	if err != nil {
		t.Fatal(err)
	}
	orig := "data:image/png;base64," + base64.StdEncoding.EncodeToString([]byte{0x89, 0x50, 0x4E, 0x47})
	ctx, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
	defer cancel()
	got := Enhance(ctx, cfg, plan, orig)
	if got != orig {
		t.Fatalf("Enhance should fall back to original on failure, got %q", got)
	}
}

// TestEnhanceNilPlan plan 为 nil / factor=1 时原样返回。
func TestEnhanceNilPlan(t *testing.T) {
	if got := Enhance(nil, &Config{}, nil, "data:image/png;base64,AAA"); got != "data:image/png;base64,AAA" {
		t.Fatalf("Enhance(nil plan) = %q", got)
	}
	plan := &Plan{SourceSize: "1024x1024", Factor: 1}
	if got := Enhance(nil, &Config{}, plan, "data:image/png;base64,AAA"); got != "data:image/png;base64,AAA" {
		t.Fatalf("Enhance(factor=1) = %q", got)
	}
}
