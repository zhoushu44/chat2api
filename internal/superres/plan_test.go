package superres

import (
	"math"
	"testing"
)

// TestPlanSizeAliases 别名分支（对等 Python size_plan）。
func TestPlanSizeAliases(t *testing.T) {
	cases := []struct {
		in      string
		factor  int
		targetW int
		alias   bool
	}{
		{"", 1, 0, true},
		{"auto", 1, 0, true},
		{"AUTO", 1, 0, true},
		{"1k", 1, 1024, true},
		{"2k", 2, 2048, true},
		{"4k", 4, 3840, true},
	}
	for _, c := range cases {
		p, err := PlanSize(c.in)
		if err != nil {
			t.Fatalf("PlanSize(%q) error: %v", c.in, err)
		}
		if p.Factor != c.factor {
			t.Errorf("PlanSize(%q).Factor = %d, want %d", c.in, p.Factor, c.factor)
		}
		if p.Alias != c.alias {
			t.Errorf("PlanSize(%q).Alias = %v, want %v", c.in, p.Alias, c.alias)
		}
		if c.targetW > 0 && (p.Target == nil || p.Target.W != c.targetW) {
			t.Errorf("PlanSize(%q).Target = %v, want W=%d", c.in, p.Target, c.targetW)
		}
	}
}

// TestPlanSizeExplicit2K4KAccepted 本地改动：显式 2K/4K 尺寸必须被接受
// （旧实现因总像素上限/16 倍数校验直接拒绝这些标准尺寸）。
func TestPlanSizeExplicit2K4KAccepted(t *testing.T) {
	cases := []struct {
		in     string
		factor int
		w, h   int
	}{
		{"2048x2048", 2, 2048, 2048},
		{"2048x1024", 2, 2048, 1024},
		{"1536x1536", 2, 1536, 1536},
		{"3840x2160", 4, 3840, 2160}, // 标准 4K UHD
		{"3840x2400", 4, 3840, 2400},
		{"2560x1440", 4, 2560, 1440}, // 标准 2K QHD
		{"4096x4096", 4, 4096, 4096}, // 标准 4K DCI
		{"1920x1080", 2, 1920, 1080}, // 非 16 倍数，也应接受
	}
	for i, c := range cases {
		p, err := PlanSize(c.in)
		if err != nil {
			t.Errorf("case %d PlanSize(%q) unexpected error: %v", i, c.in, err)
			continue
		}
		if p.Factor != c.factor {
			t.Errorf("case %d PlanSize(%q).Factor = %d, want %d", i, c.in, p.Factor, c.factor)
		}
		if p.Target == nil || p.Target.W != c.w || p.Target.H != c.h {
			t.Errorf("case %d PlanSize(%q).Target = %v, want %dx%d", i, c.in, p.Target, c.w, c.h)
		}
		if !p.Exact {
			t.Errorf("case %d PlanSize(%q).Exact = false, want true", i, c.in)
		}
	}
}

// TestPlanSizeProperties 校验尺寸规划的关键性质：
//  1. 源图 × factor 后覆盖目标（可下采样，避免欠采样拉伸）
//  2. 源图宽高比接近目标（±8% 内），防止精确缩放产生明显变形
//  3. 源图像素不低于下限、超分后单边不超过腾讯云上限
func TestPlanSizeProperties(t *testing.T) {
	inputs := []string{
		"2048x2048", "3840x3840", "3840x2160", "2560x1440", "1920x1080",
		"4096x4096", "4096x2160", "3200x1800", "1280x720", "1024x1024",
		"2048x1024", "1536x1536", "3840x2400",
	}
	for _, in := range inputs {
		p, err := PlanSize(in)
		if err != nil {
			t.Errorf("PlanSize(%q) error: %v", in, err)
			continue
		}
		if p.Factor <= 1 || p.Target == nil {
			continue
		}
		src, err := ParseSize(p.SourceSize)
		if err != nil {
			t.Errorf("PlanSize(%q).SourceSize %q unparsable: %v", in, p.SourceSize, err)
			continue
		}
		// 1) 覆盖目标
		if src.W*p.Factor < p.Target.W || src.H*p.Factor < p.Target.H {
			t.Errorf("PlanSize(%q): 源图 %s ×%d 未覆盖目标 %s",
				in, p.SourceSize, p.Factor, p.Target.String())
		}
		// 2) 宽高比守恒
		srcRatio := float64(src.W) / float64(src.H)
		dstRatio := float64(p.Target.W) / float64(p.Target.H)
		if math.Abs(srcRatio-dstRatio)/dstRatio > 0.08 {
			t.Errorf("PlanSize(%q): 源图宽高比 %.3f 偏离目标 %.3f 超过 8%%（源 %s）",
				in, srcRatio, dstRatio, p.SourceSize)
		}
		// 3) 像素与单边约束
		if src.W*src.H < minPixels {
			t.Errorf("PlanSize(%q): 源图像素 %d 低于下限 %d", in, src.W*src.H, minPixels)
		}
		if m := maxDim(Size{W: src.W * p.Factor, H: src.H * p.Factor}); m > upscaleCeiling {
			t.Errorf("PlanSize(%q): 超分后单边 %d 超过上限 %d", in, m, upscaleCeiling)
		}
	}
}

// TestPlanSizeErrors 校验失败分支。
func TestPlanSizeErrors(t *testing.T) {
	cases := []string{
		"4112x4112", // 超过长边上限（>4096）
		"2048x16",   // 宽高比超 3:1
		"256x256",   // 像素不足
		"768x768",   // 像素不足
		"1024x576",  // 像素不足
		"abc",       // 非格式
		"1024x",     // 非格式
	}
	for _, c := range cases {
		if _, err := PlanSize(c); err == nil {
			t.Errorf("PlanSize(%q) expected error, got nil", c)
		}
	}
}

// TestBuildPostProcessRule 后处理规则组装（精确缩放 + 转码）。
func TestBuildPostProcessRule(t *testing.T) {
	plan := &Plan{Factor: 4, Exact: true, Target: &Size{W: 3840, H: 2160}}

	got := buildPostProcessRule(plan, &Config{}, "")
	if want := "imageMogr2/thumbnail/3840x2160!"; got != want {
		t.Errorf("buildPostProcessRule(no format) = %q, want %q", got, want)
	}
	got = buildPostProcessRule(plan, &Config{}, "jpeg")
	if want := "imageMogr2/thumbnail/3840x2160!/format/jpeg/quality/90"; got != want {
		t.Errorf("buildPostProcessRule(jpeg) = %q, want %q", got, want)
	}
	got = buildPostProcessRule(plan, &Config{DisableExactSize: true}, "webp")
	if want := "imageMogr2/format/webp/quality/90"; got != want {
		t.Errorf("buildPostProcessRule(disable exact) = %q, want %q", got, want)
	}
	if got := buildPostProcessRule(&Plan{Factor: 4}, &Config{}, ""); got != "" {
		t.Errorf("buildPostProcessRule(empty) = %q, want \"\"", got)
	}
}
