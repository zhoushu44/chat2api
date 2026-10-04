package superres

import (
	"context"
	"encoding/base64"

	"chatgpt2api/internal/config"
)

// ---- 接线辅助：供生图 handler 以最少行数接入 ------------------------------
//
// 用法（images.go / edits.go）：
//
//	plan := superres.PlanFromRequest(req.Size)     // 1 行：判断是否接管
//	size := superres.SizeOr(plan, req.Size)        // 1 行：源图尺寸 hint
//	... orchestrator 生成 ...
//	data := superres.ApplyB64(c, plan, res.B64)    // 1 行：后处理（逐张）
//
// 删除功能时移除这三行 + import 即可，本包其余代码不受影响。

// FromConfig 从全局配置读取超分段（nil 安全）。
func FromConfig() *Config {
	cfg := config.Get()
	if cfg == nil {
		return nil
	}
	sr := cfg.SuperResolution
	return &Config{
		Enabled:          sr.Enabled,
		SecretID:         sr.SecretID,
		SecretKey:        sr.SecretKey,
		Bucket:           sr.Bucket,
		Region:           sr.Region,
		PublicBaseURL:    sr.PublicBaseURL,
		UploadEndpoint:   sr.UploadEndpoint,
		OutputFormat:     sr.OutputFormat,
		OutputQuality:    sr.OutputQuality,
		DisableExactSize: sr.DisableExactSize,
	}
}

// PlanFromRequest 便捷入口：开关 + 尺寸判定一步完成。
// 返回 nil 表示本次请求不接管（调用方完全走原链路，零行为变化）。
func PlanFromRequest(size string) *Plan {
	return ShouldEnhance(FromConfig(), size)
}

// SizeOr 源图尺寸 hint：plan 接管时返回源图尺寸，否则原样返回用户 size。
func SizeOr(plan *Plan, size string) string {
	if plan != nil && plan.SourceSize != "" {
		return plan.SourceSize
	}
	return size
}

// ApplyB64 对一张 base64 图片字节执行超分。
// 返回值为增强后的内容：成功 = 公网 URL（string 形态装回 []byte），
// 失败/不接管 = 原字节原样返回。
// 注意：成功时返回的 []byte 内容是 URL 文本 —— 调用方约定见 ResultKind。
func ApplyB64(ctx context.Context, plan *Plan, b64 []byte) Result {
	if plan == nil || plan.Factor <= 1 || len(b64) == 0 {
		return Result{Data: b64, Kind: KindB64}
	}
	// b64 已是 base64 文本（orchestrator 下载图片后编码过一次），
	// 直接拼 dataURL —— 不能再编码第二次（双重 base64 会让超分上传
	// 的 body 是 ASCII 文本而非图片字节，腾讯 CI 报 InvalidImageFormat）。
	dataURL := "data:image/png;base64," + string(b64)
	out := Enhance(ctx, FromConfig(), plan, dataURL)
	if out == dataURL {
		// 降级：原图返回（b64 形态不变）
		return Result{Data: b64, Kind: KindB64}
	}
	// 成功：out 为公网 URL
	return Result{Data: []byte(out), Kind: KindURL}
}

// Result 增强结果（区分 b64 与 URL 两种形态）。
type Result struct {
	Data []byte
	Kind ResultKind
}

// ResultKind 结果形态。
type ResultKind int

const (
	KindB64 ResultKind = iota // Data 为图片原始字节
	KindURL                   // Data 为公网 URL 文本
)

// IsURL 是否为 URL 形态（调用方据此把 b64_json 换成 url 字段）。
func (r Result) IsURL() bool { return r.Kind == KindURL }

// URL 取 URL 文本（非 URL 形态返回空串）。
func (r Result) URL() string {
	if r.IsURL() {
		return string(r.Data)
	}
	return ""
}

// base64Std 标准编码小工具。
func base64Std(b []byte) string {
	return base64.StdEncoding.EncodeToString(b)
}
