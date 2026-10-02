package superres

import "testing"

// TestPlanSizeAliases 对等 Python size_plan 的别名分支。
func TestPlanSizeAliases(t *testing.T) {
	cases := []struct {
		in         string
		source     string
		factor     int
		targetW    int
		alias      bool
	}{
		{"", "auto", 1, 0, true},
		{"auto", "auto", 1, 0, true},
		{"AUTO", "auto", 1, 0, true},
		{"1k", "1024x1024", 1, 1024, true},
		// 2k 源图 512x512 像素不足，补到 1024x1024（对等 Python while 循环）
		{"2k", "1024x1024", 2, 2048, true},
		// 4k 源图 960x960 像素充足（921600 ≥ 655360）
		{"4k", "960x960", 4, 3840, true},
	}
	for _, c := range cases {
		p, err := PlanSize(c.in)
		if err != nil {
			t.Fatalf("PlanSize(%q) error: %v", c.in, err)
		}
		if p.SourceSize != c.source {
			t.Errorf("PlanSize(%q).SourceSize = %q, want %q", c.in, p.SourceSize, c.source)
		}
		if p.Factor != c.factor {
			t.Errorf("PlanSize(%q).Factor = %d, want %d", c.in, p.Factor, c.factor)
		}
		if p.Target != nil && p.Target.W != c.targetW {
			t.Errorf("PlanSize(%q).Target.W = %d, want %d", c.in, p.Target.W, c.targetW)
		}
		if p.Alias != c.alias {
			t.Errorf("PlanSize(%q).Alias = %v, want %v", c.in, p.Alias, c.alias)
		}
	}
}

// TestPlanSizeCustom 对等 Python size_plan 的自定义尺寸分支。
func TestPlanSizeCustom(t *testing.T) {
	cases := []struct {
		in     string
		source string
		factor int
	}{
		// 长边 ≤1024：不超分（像素需 ≥ 655360，即 ≥ 832x832 量级）
		{"1024x704", "1024x704", 1},
		{"832x832", "832x832", 1},
		// 长边 1025~2048：2 倍超分，源图 ≈ 1/2（像素补齐后对齐 Python 参考值）
		{"2048x1024", "1024x640", 2},
		{"1536x1536", "816x816", 2},
		// 长边 2049~3840：4 倍超分，源图 ≈ 1/4
		{"3840x1920", "960x688", 4},
		{"2560x1440", "816x816", 4},
	}
	for _, c := range cases {
		p, err := PlanSize(c.in)
		if err != nil {
			t.Fatalf("PlanSize(%q) error: %v", c.in, err)
		}
		if p.SourceSize != c.source {
			t.Errorf("PlanSize(%q).SourceSize = %q, want %q", c.in, p.SourceSize, c.source)
		}
		if p.Factor != c.factor {
			t.Errorf("PlanSize(%q).Factor = %d, want %d", c.in, p.Factor, c.factor)
		}
	}
}

// TestPlanSizeErrors 校验失败分支（对等 Python 抛出的 ValueError 文案）。
func TestPlanSizeErrors(t *testing.T) {
	cases := []string{
		"1023x1023",  // 非 16 倍数
		"1000x1010", // 非 16 倍数
		"3856x3856", // 超长边
		"2048x16",   // 宽高比超 3:1（128:1）
		"256x256",   // 像素不足
		"768x768",   // 像素不足（589824 < 655360）
		"1024x576",  // 像素不足（589824 < 655360）
		"3840x2400", // 像素超限（自定义，非别名）
		"abc",       // 非法格式
		"1024x",     // 非法格式
	}
	for _, c := range cases {
		if _, err := PlanSize(c); err == nil {
			t.Errorf("PlanSize(%q) expected error, got nil", c)
		}
	}
}

// TestPlanSizeAliasPixelLimit 别名放宽像素上限（4k=3840x3840 > 8M 像素但允许）。
func TestPlanSizeAliasPixelLimit(t *testing.T) {
	p, err := PlanSize("4k")
	if err != nil {
		t.Fatalf("PlanSize(4k) error: %v", err)
	}
	if p.Factor != 4 {
		t.Fatalf("PlanSize(4k).Factor = %d, want 4", p.Factor)
	}
	// 源图 3840/4=960，目标 3840x3840
	if p.SourceSize != "960x960" {
		t.Errorf("PlanSize(4k).SourceSize = %q, want 960x960", p.SourceSize)
	}
}
