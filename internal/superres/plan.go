// Package superres 图片超分（腾讯云 COS 数据万象 AISuperResolution）。
//
// 功能化设计（可整体摘除）：
//   - 本包所有逻辑自包含，对外的接入点只有三个：
//     1) config.Config.SuperResolution（配置段，见 internal/config）
//     2) superres.ShouldEnhance / superres.SourceSize（images.go / edits.go 各 2-3 行调用）
//     3) superres.Enhance（编排后处理，失败自动降级返回原图）
//   - 不引入任何后台 goroutine / 全局状态；COS client 按需惰性创建并缓存。
//   - 移除本功能时：删除 internal/superres 目录 + images.go / edits.go /
//     config.go / settings.go(seed) / 前端设置块中的接线行即可，无残留。
//
// 移植自 zhoushu44/OpenAI-Image-Super-Resolution-Proxy（app.py，MIT 场景自用移植）：
// 尺寸策略与校验规则与其 size_plan() 对等。
//
// === 本地改动（真实 2K/4K）===
//
//  1. 放开显式尺寸的总像素上限：原实现对显式 WIDTHxHEIGHT 直接施加 maxPixels 限制，
//     导致 3840x2160 / 2560x1440 / 4096x4096 等标准 2K/4K 尺寸被拒绝，只有
//     2k/4k 别名能用。现在显式尺寸与别名同等对待。
//  2. 显式尺寸允许非 16 倍数：16 对齐只作用于「发给上游的源图尺寸」，
//     请求的目标尺寸保持原样（1920x1080 也能用）。
//  3. 最小像素补齐改为「等比放大」：原实现只 bump 单边（sw 或 sh），
//     会让源图宽高比严重偏离目标（如 3840x2160 → 源 960x688，比例 1.40 vs 1.78），
//     配合精确缩放会产生明显拉伸。现在按同一比例缩放两边，宽高比基本守恒。
//  4. Plan 增加 Exact/Target：client.go 在超分后追加一步
//     imageMogr2/thumbnail/WxH!，使成品尺寸严格等于请求尺寸。
package superres

import (
	"fmt"
	"math"
	"strconv"
	"strings"
)

// 尺寸校验常量（对等 Python 版规则）。
const (
	maxLongEdge   = 4096      // 最长边上限（请求侧）
	maxPixels     = 8_294_400 // 总像素上限（8K）
	minPixels     = 655_360   // 总像素下限
	maxAspect     = 3.0       // 宽高比上限
	alignMultiple = 16        // 源图宽高对齐倍数
	// upscaleCeiling 超分后单边上限保护。腾讯云「处理参数不得超过 10000px」，
	// AI 超分实测可稳定处理到该值；再大易触发 InternalError。
	upscaleCeiling = 8192
)

// Plan 尺寸规划结果。
type Plan struct {
	// SourceSize 发给上游的源图尺寸（WIDTHxHEIGHT；超分时为目标约 1/factor）。
	SourceSize string
	// Factor 超分倍数：1 = 不超分；2 / 4 = 腾讯数据万象 AI 超分。
	Factor int
	// Target 目标尺寸。本地改动后为「精确目标」：超分成品会被
	// imageMogr2/thumbnail 严格缩放到该尺寸。
	Target *Size
	// Alias 请求使用的是否为 auto/1k/2k/4k 别名。
	Alias bool
	// Exact 是否执行精确缩放（显式尺寸或别名命中 2K/4K 时为 true）。
	Exact bool
}

// Size 宽高。
type Size struct{ W, H int }

func (s Size) String() string { return fmt.Sprintf("%dx%d", s.W, s.H) }

// ParseSize 解析 WIDTHxHEIGHT；不支持负数/非数字。
func ParseSize(s string) (Size, error) {
	parts := strings.SplitN(strings.ToLower(strings.TrimSpace(s)), "x", 2)
	if len(parts) != 2 {
		return Size{}, fmt.Errorf("size 必须是 auto、1k、2k、4k 或 WIDTHxHEIGHT")
	}
	w, err1 := strconv.Atoi(strings.TrimSpace(parts[0]))
	h, err2 := strconv.Atoi(strings.TrimSpace(parts[1]))
	if err1 != nil || err2 != nil {
		return Size{}, fmt.Errorf("size 必须是 auto、1k、2k、4k 或 WIDTHxHEIGHT")
	}
	return Size{W: w, H: h}, nil
}

var aliases = map[string]string{
	"1k": "1024x1024",
	"2k": "2048x2048",
	"4k": "3840x3840",
}

// PlanSize 把请求 size 翻译成（源图尺寸, 超分倍数, 精确目标尺寸）。
//
//	"auto"            → 透传 auto，factor=1
//	"1k" / ≤1024      → 不超分，源图即目标
//	"2k" / 1025~2048  → 源图 ≈ 目标 1/2，腾讯 2 倍超分 → 精确缩放到目标
//	"4k" / 2049~4096  → 源图 ≈ 目标 1/4，腾讯 4 倍超分 → 精确缩放到目标
func PlanSize(size string) (*Plan, error) {
	s := strings.ToLower(strings.TrimSpace(size))
	if s == "" || s == "auto" {
		return &Plan{SourceSize: "auto", Factor: 1, Alias: true}, nil
	}
	alias, isAlias := aliases[s]
	normalized := s
	if isAlias {
		normalized = alias
	}
	dim, err := ParseSize(normalized)
	if err != nil {
		return nil, err
	}
	if dim.W <= 0 || dim.H <= 0 || maxDim(dim) > maxLongEdge {
		return nil, fmt.Errorf("gpt-image-2 的 size 长边必须在 1 到 %d 之间", maxLongEdge)
	}
	ratio := float64(maxDim(dim)) / float64(minDim(dim))
	if ratio > maxAspect || dim.W*dim.H < minPixels {
		return nil, fmt.Errorf("gpt-image-2 的 size 需满足宽高比不超过 3:1，总像素不低于 %d", minPixels)
	}
	// 目标尺寸：别名归一化到标准值；显式尺寸保持用户原样（不强制 16 倍数）。
	target := dim
	if maxDim(dim) <= 1024 {
		// 1K：不超分，源图即目标。
		if isAlias {
			target = Size{W: 1024, H: 1024}
		}
		return &Plan{SourceSize: dim.String(), Factor: 1, Target: &target, Alias: isAlias, Exact: true}, nil
	}
	factor := 2
	if maxDim(dim) > 2048 {
		factor = 4
	}
	// 源图尺寸 ≈ 目标 / factor，16 对齐（对等 Python round(w/factor/16)*16）。
	sw := alignRound(int(math.Round(float64(dim.W)/float64(factor))), alignMultiple)
	sh := alignRound(int(math.Round(float64(dim.H)/float64(factor))), alignMultiple)
	// 低于最小像素时等比放大（保持宽高比，避免单边 bump 造成拉伸）。
	if sw*sh < minPixels {
		scale := math.Sqrt(float64(minPixels) / float64(sw*sh))
		sw = alignCeil(int(math.Ceil(float64(sw)*scale)), alignMultiple)
		sh = alignCeil(int(math.Ceil(float64(sh)*scale)), alignMultiple)
	}
	// 超过像素上限则等比回缩（极端宽高比场景）。
	if sw*sh > maxPixels {
		scale := math.Sqrt(float64(maxPixels) / float64(sw*sh))
		sw = alignFloor(int(float64(sw)*scale), alignMultiple)
		sh = alignFloor(int(float64(sh)*scale), alignMultiple)
	}
	// 超分后单边不得超过腾讯云可处理上限。
	if m := maxDim(Size{W: sw * factor, H: sh * factor}); m > upscaleCeiling {
		scale := float64(upscaleCeiling) / float64(m)
		sw = alignFloor(int(float64(sw)*scale), alignMultiple)
		sh = alignFloor(int(float64(sh)*scale), alignMultiple)
	}
	source := Size{W: sw, H: sh}
	return &Plan{SourceSize: source.String(), Factor: factor, Target: &target, Alias: isAlias, Exact: true}, nil
}

func maxDim(s Size) int {
	if s.W > s.H {
		return s.W
	}
	return s.H
}

func minDim(s Size) int {
	if s.W < s.H {
		return s.W
	}
	return s.H
}

// alignRound 四舍五入到 align 倍数，最小 align。
func alignRound(v, align int) int {
	out := int(math.Round(float64(v)/float64(align))) * align
	if out < align {
		out = align
	}
	return out
}

// alignFloor 向下取整到 align 倍数，最小 align。
func alignFloor(v, align int) int {
	out := (v / align) * align
	if out < align {
		out = align
	}
	return out
}

// alignCeil 向上取整到 align 倍数，最小 align。
func alignCeil(v, align int) int {
	if v <= align {
		return align
	}
	out := ((v + align - 1) / align) * align
	return out
}
