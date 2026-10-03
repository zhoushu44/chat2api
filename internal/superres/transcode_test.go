package superres

import "testing"

// TestNormalizeOutputFormat 输出格式归一化。
func TestNormalizeOutputFormat(t *testing.T) {
	cases := []struct{ in, want string }{
		{"webp", "webp"},
		{" WEBP ", "webp"},
		{"Webp", "webp"},
		{"jpeg", "jpeg"},
		{"jpg", "jpeg"},
		{"JPEG", "jpeg"},
		{"", ""},          // 默认：保持无损 PNG
		{"png", ""},       // png = 无损，不转码
		{"avif", ""},      // 未支持格式回落无损
		{"unknown", ""},   // 未知格式回落无损
	}
	for _, c := range cases {
		if got := normalizeOutputFormat(c.in); got != c.want {
			t.Errorf("normalizeOutputFormat(%q) = %q, want %q", c.in, got, c.want)
		}
	}
}

// TestOutputQuality 质量参数收敛（默认 90，越界收敛）。
func TestOutputQuality(t *testing.T) {
	cases := []struct {
		in   int
		want int
	}{
		{0, 90},   // 未设置 → 默认
		{90, 90},  // 常规
		{85, 85},  // 显式低档
		{60, 60},  // 下边界
		{95, 95},  // 上边界
		{10, 90},  // 过低 → 默认
		{100, 90}, // 过高 → 默认
	}
	for _, c := range cases {
		cfg := &Config{OutputQuality: c.in}
		if got := cfg.outputQuality(); got != c.want {
			t.Errorf("outputQuality(in=%d) = %d, want %d", c.in, got, c.want)
		}
	}
}

// TestCompressToggle 勾选框语义：compress=true → jpeg；false → 清空。
func TestCompressToggle(t *testing.T) {
	// normalizeOutputFormat 对 jpeg 的映射（config 侧 applySuperResolution 直接写 "jpeg"）
	if got := normalizeOutputFormat("jpeg"); got != "jpeg" {
		t.Fatalf("jpeg normalize = %q", got)
	}
	// 空 = 不转码（无损 PNG）
	if got := normalizeOutputFormat(""); got != "" {
		t.Fatalf("empty normalize = %q", got)
	}
}
