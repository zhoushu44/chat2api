package utils

import (
	"bytes"
	"image"
	_ "image/jpeg"
	_ "image/png"
	"math"
	"strings"
)

// 图片 token 估费（P2.8）：对等 utils/image_tokens.py 全量移植。
// patch 模型（32px patch + 模型乘数 + budget/shrink）与 tile 模型（512px tile + 高低费率）双算法。

const (
	patchSize          = 32
	tileSize           = 512
	tileHighShortSide  = 768
	imageInputModel    = "gpt-5.4-mini"
	defaultImageWidth  = 1024
	defaultImageHeight = 1024
)

// patch1536Models 1536-budget 模型前缀。
var patch1536Models = []string{
	"gpt-5.4-mini", "gpt-5.4-nano", "gpt-5-mini", "gpt-5-nano",
	"gpt-5.2", "gpt-5.3-codex", "gpt-5-codex-mini", "gpt-5.1-codex-mini",
	"gpt-5.2-codex", "gpt-5.2-chat-latest", "o4-mini", "gpt-4.1-mini", "gpt-4.1-nano",
}

// patchMultipliers 模型乘数表。
var patchMultipliers = map[string]float64{
	"gpt-5.4-mini": 1.62,
	"gpt-5.4-nano": 2.46,
	"gpt-5-mini":   1.62,
	"gpt-5-nano":   2.46,
	"gpt-4.1-mini": 1.62,
	"gpt-4.1-nano": 2.46,
	"o4-mini":      1.72,
}

func modelName(model string) string {
	return strings.ToLower(strings.TrimSpace(model))
}

func patchCount(w, h float64) int {
	return int(math.Ceil(w/patchSize) * math.Ceil(h/patchSize))
}

func patchMultiplier(model string) float64 {
	name := modelName(model)
	for prefix, mult := range patchMultipliers {
		if strings.HasPrefix(name, prefix) {
			return mult
		}
	}
	return 1.0
}

// patchLimits 返回 (patchBudget, maxDimension, ok)。
func patchLimits(model, detail string) (int, int, bool) {
	name := modelName(model)
	for _, prefix := range patch1536Models {
		if strings.HasPrefix(name, prefix) {
			return 1536, 2048, true
		}
	}
	if strings.HasPrefix(name, "gpt-5.5") {
		if detail == "auto" || detail == "original" {
			return 10000, 6000, true
		}
		return 2500, 2048, true
	}
	if strings.HasPrefix(name, "gpt-5.4") {
		if detail == "original" {
			return 10000, 6000, true
		}
		return 2500, 2048, true
	}
	return 0, 0, false
}

func patchTokens(width, height int, model, detail string) int {
	multiplier := patchMultiplier(model)
	if detail == "low" {
		return int(math.Ceil(256 * multiplier))
	}
	budget, maxDim, ok := patchLimits(model, detail)
	if !ok {
		return 0
	}
	scale := math.Min(1.0, float64(maxDim)/float64(max(width, height)))
	rw := float64(width) * scale
	rh := float64(height) * scale
	if patchCount(rw, rh) > budget {
		shrink := math.Sqrt(float64(patchSize*patchSize*budget) / (rw * rh))
		wUnits := rw * shrink / patchSize
		hUnits := rh * shrink / patchSize
		adj := shrink
		if wUnits > 0 && hUnits > 0 {
			adj = shrink * math.Min(math.Floor(wUnits)/wUnits, math.Floor(hUnits)/hUnits)
		}
		rw *= adj
		rh *= adj
	}
	tokens := patchCount(math.Max(1, rw), math.Max(1, rh))
	if tokens > budget {
		tokens = budget
	}
	return int(math.Ceil(float64(tokens) * multiplier))
}

func tileRates(model string) (int, int) {
	name := modelName(model)
	if name == "gpt-5" || name == "gpt-5-chat-latest" {
		return 70, 140
	}
	if strings.HasPrefix(name, "gpt-4o-mini") {
		return 2833, 5667
	}
	if strings.HasPrefix(name, "o1") || strings.HasPrefix(name, "o1-pro") || strings.HasPrefix(name, "o3") {
		return 75, 150
	}
	if strings.HasPrefix(name, "computer-use-preview") {
		return 65, 129
	}
	return 85, 170
}

func tileTokens(width, height int, model, detail string) int {
	base, perTile := tileRates(model)
	if detail == "low" {
		return base
	}
	scale := math.Min(1.0, 2048/math.Max(float64(width), float64(height)))
	rw := float64(width) * scale
	rh := float64(height) * scale
	if short := math.Min(rw, rh); short > 0 {
		s := float64(tileHighShortSide) / short
		rw *= s
		rh *= s
	}
	tiles := int(math.Ceil(rw/tileSize) * math.Ceil(rh/tileSize))
	return base + tiles*perTile
}

// CountImageInputTokens 输入图片 token（对等 count_image_input_tokens；固定 patch 模型）。
func CountImageInputTokens(width, height int, model, detail string) int {
	if width <= 0 || height <= 0 {
		return 0
	}
	detail = strings.ToLower(strings.TrimSpace(detail))
	if detail == "" {
		detail = "auto"
	}
	return patchTokens(width, height, imageInputModel, detail)
}

// CountImageTileTokens tile 模型计数（导出供测试/对比）。
func CountImageTileTokens(width, height int, model, detail string) int {
	if width <= 0 || height <= 0 {
		return 0
	}
	detail = strings.ToLower(strings.TrimSpace(detail))
	if detail == "" {
		detail = "auto"
	}
	return tileTokens(width, height, model, detail)
}

// CountGeneratedImageTokens 生成图片 token（对等 count_generated_image_tokens）。
func CountGeneratedImageTokens(width, height int, quality string) int {
	patches := patchCount(float64(width), float64(height))
	switch strings.ToLower(strings.TrimSpace(quality)) {
	case "low":
		return int(math.Ceil(float64(patches) * 17 / 64))
	case "high", "hd":
		return int(math.Ceil(float64(patches) * 65 / 16))
	default:
		return int(math.Ceil(float64(patches) * 33 / 32))
	}
}

// CountImageOutputTokens 输出图片 token（对等 count_image_output_tokens）。
func CountImageOutputTokens(size, quality string, count int) int {
	w, h := ParseImageSize(size)
	if count < 0 {
		count = 0
	}
	return count * CountGeneratedImageTokens(w, h, quality)
}

// imageDecodeConfig 图片字节解码尺寸（stdlib）。
func imageDecodeConfig(data []byte) (int, int, error) {
	cfg, _, err := image.DecodeConfig(bytes.NewReader(data))
	if err != nil {
		return 0, 0, err
	}
	return cfg.Width, cfg.Height, nil
}

// EstimateImageTokens 旧签名兼容 → patch 模型（替代旧 tiles*85+85 近似）。
func EstimateImageTokens(width, height int) int {
	return CountImageInputTokens(width, height, "", "auto")
}

// EstimateTextTokens 旧签名兼容 → 真实 BPE。
func EstimateTextTokens(text string) int {
	return CountTokens(text)
}
