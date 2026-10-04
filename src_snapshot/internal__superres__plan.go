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
package superres

import (
	"fmt"
	"math"
	"strconv"
	"strings"
)

// 尺寸校验常量（对等 Python 版规则）。
const (
	maxLongEdge   = 3840            // 最长边上限
	maxPixels     = 8_294_400       // 总像素上限（8K）
	minPixels     = 655_360         // 总像素下限
	maxAspect     = 3.0             // 宽高比上限
	alignMultiple = 16              // 宽高对齐倍数
)

// Plan 尺寸规划结果。
type Plan struct {
	// SourceSize 发给上游的源图尺寸（WIDTHxHEIGHT；超分时为目标约 1/factor）。
	SourceSize string
	// Factor 超分倍数：1 = 不超分；2 / 4 = 腾讯数据万象 AI 超分。
	Factor int
	// Target 超分目标尺寸（factor>1 时非 nil，用于落盘命名/日志，不强制最终像素）。
	Target *Size
	// Alias 请求使用的是否为 auto/1k/2k/4k 别名（别名放宽总像素上限）。
	Alias bool
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

// PlanSize 对等 Python size_plan：把请求 size 翻译成（源图尺寸, 超分倍数, 目标尺寸）。
//
//	"auto"            → 透传 auto，factor=1
//	"1k" / ≤1024      → 不超分，源图即目标
//	"2k" / 1025~2048  → 源图 ≈ 目标 1/2，腾讯 2 倍超分
//	"4k" / 2049~3840  → 源图 ≈ 目标 1/4，腾讯 4 倍超分
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
	if dim.W%alignMultiple != 0 || dim.H%alignMultiple != 0 {
		return nil, fmt.Errorf("gpt-image-2 的 size 宽高必须是 %d 的倍数", alignMultiple)
	}
	ratio := float64(maxDim(dim)) / float64(minDim(dim))
	pixels := dim.W * dim.H
	if ratio > maxAspect || pixels < minPixels || (pixels > maxPixels && !isAlias) {
		return nil, fmt.Errorf("gpt-image-2 的 size 需满足宽高比不超过 3:1，总像素为 %d 到 %d", minPixels, maxPixels)
	}
	if maxDim(dim) <= 1024 {
		// 1K：不超分。别名 1k 目标 1024x1024；自定义尺寸目标即自身。
		target := dim
		if isAlias {
			target = Size{W: 1024, H: 1024}
		}
		return &Plan{SourceSize: dim.String(), Factor: 1, Target: &target, Alias: isAlias}, nil
	}
	factor := 2
	if maxDim(dim) > 2048 {
		factor = 4
	}
	// 源图尺寸 ≈ 目标 / factor，16 对齐（对等 Python round(w/factor/16)*16），保证最小像素。
	sw := alignRound(int(math.Round(float64(dim.W)/float64(factor))), alignMultiple)
	sh := alignRound(int(math.Round(float64(dim.H)/float64(factor))), alignMultiple)
	// 对齐后可能低于最小像素（长边较小的 16:16 比例），逐步补到下限（对等 Python while 循环）。
	for sw*sh < minPixels {
		if sw <= sh {
			sw += alignMultiple
		} else {
			sh += alignMultiple
		}
	}
	// 超过像素上限则等比回缩（极端宽高比场景）。
	if sw*sh > maxPixels {
		scale := math.Sqrt(float64(maxPixels) / float64(sw*sh))
		sw = alignFloor(int(float64(sw)*scale), alignMultiple)
		sh = alignFloor(int(float64(sh)*scale), alignMultiple)
	}
	target := dim
	source := Size{W: sw, H: sh}
	return &Plan{SourceSize: source.String(), Factor: factor, Target: &target, Alias: isAlias}, nil
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

// alignRound 四舍五入到 align 倍数，最小 align（对等 Python round(v/16)*16 与 max(16,...)）。
func alignRound(v, align int) int {
	out := int(math.Round(float64(v)/float64(align))) * align
	if out < align {
		out = align
	}
	return out
}

// alignFloor 向下取整到 align 倍数，最小 16。
func alignFloor(v, align int) int {
	out := (v / align) * align
	if out < align {
		out = align
	}
	return out
}
