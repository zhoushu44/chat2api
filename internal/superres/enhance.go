package superres

import (
	"context"
	"encoding/base64"
	"log"
	"strings"
	"sync/atomic"
	"time"
)

// Config 超分配置（settings.json super_resolution 段 → config.SuperResolution）。
type Config struct {
	Enabled       bool   // 总开关
	SecretID      string // 腾讯云 SecretId
	SecretKey     string // 腾讯云 SecretKey
	Bucket        string // COS Bucket（含 APPID）
	Region        string // COS 地域，如 ap-guangzhou
	PublicBaseURL string // 成品公网前缀，如 https://bucket-appid.cos.ap-guangzhou.myqcloud.com
	UploadEndpoint string // 可选上传端点（全球加速），如 cos.accelerate.myqcloud.com
	// OutputFormat 可选输出转码：webp / jpeg（空或 png = 保持无损 PNG）。
	// 4K 无损 PNG 单张 15~25MB，转 webp q85 约 1~2MB（实测 24MB→1.15MB）。
	OutputFormat string
	// OutputQuality 转码质量 60~95（默认 85，仅 OutputFormat 非空时生效）。
	OutputQuality int
}

// Ready 配置是否满足超分执行条件（全部凭证齐备）。
func (c *Config) Ready() bool {
	return c != nil && c.Enabled &&
		strings.TrimSpace(c.SecretID) != "" &&
		strings.TrimSpace(c.SecretKey) != "" &&
		strings.TrimSpace(c.Bucket) != "" &&
		strings.TrimSpace(c.Region) != "" &&
		strings.TrimSpace(c.PublicBaseURL) != ""
}

// ShouldEnhance 判断一次生图请求是否需要走超分链路。
// 三个条件全满足才接管：开关开 + size 命中 2K/4K 档 + 尺寸校验通过。
// 返回 nil 表示本次请求不接管（调用方走原链路，零行为变化）。
func ShouldEnhance(cfg *Config, size string) *Plan {
	if !cfg.Ready() {
		return nil
	}
	plan, err := PlanSize(size)
	if err != nil || plan.Factor <= 1 {
		return nil
	}
	return plan
}

// defaultClient 包级共享 client（惰性重建，见 COSClient.client）。
var defaultClient = NewCOSClient()

// Enhance 对编排器产出的图片字节执行腾讯数据万象 AI 超分。
//
// 调用契约（images.go / edits.go）：
//   - ShouldEnhance 返回 plan 后，orchestrator 用 plan.SourceSize 生成源图；
//   - Enhance 拿到源图字节后上传 COS 触发超分，返回成品公网 URL；
//   - 失败降级：返回输入原图 + 错误日志，调用方照常返回（不 502），
//     保证「开开关但不能用」时服务仍出图（可用性优先于尺寸）。
//
// 返回值：增强后内容（成功为公网 URL，失败为原 dataURL 原样回退）。
func Enhance(ctx context.Context, cfg *Config, plan *Plan, imageDataURL string) string {
	if plan == nil || plan.Factor <= 1 || imageDataURL == "" {
		return imageDataURL
	}
	started := time.Now()
	// dataURL → (bytes, contentType)
	contentType, data, ok := splitDataURL(imageDataURL)
	if !ok {
		log.Printf("[superres] skip: image is not a data URL (len=%d)", len(imageDataURL))
		return imageDataURL
	}
	resultURL, sourceKey, err := defaultClient.UploadAndSuperResolution(ctx, cfg, data, contentType, plan.Factor)
	if sourceKey != "" {
		// 无论成败都清理临时源图（对等 Python finally 分支）
		go defaultClient.DeleteSource(context.Background(), cfg, sourceKey)
	}
	if err != nil {
		log.Printf("[superres] fallback to original: %v (elapsed=%dms)", err, time.Since(started).Milliseconds())
		return imageDataURL
	}
	log.Printf("[superres] done factor=%d bytes=%d url=%s elapsed=%dms",
		plan.Factor, len(data), resultURL, time.Since(started).Milliseconds())
	return resultURL
}

// splitDataURL 解析 data:[<mediatype>][;base64],<data>。仅支持 base64 形态
// （本项目 orchestrator 产出的 dataURL 全部为 base64）。
func splitDataURL(dataURL string) (contentType string, data []byte, ok bool) {
	if !strings.HasPrefix(dataURL, "data:") {
		return "", nil, false
	}
	comma := strings.Index(dataURL, ",")
	if comma < 0 {
		return "", nil, false
	}
	header := dataURL[5:comma]
	payload := dataURL[comma+1:]
	if !strings.HasSuffix(header, ";base64") {
		return "", nil, false
	}
	contentType = strings.TrimSuffix(header, ";base64")
	if contentType == "" {
		contentType = "image/png"
	}
	decoded, err := base64.StdEncoding.DecodeString(payload)
	if err != nil || len(decoded) == 0 {
		return "", nil, false
	}
	return contentType, decoded, true
}

// EnhanceResult 供测试/上层观察的增强结果摘要。
type EnhanceResult struct {
	Applied   bool
	URL       string
	Factor    int
	ElapsedMs int64
}

// stats 简易计数（dashboard 可后续接入；当前仅日志可见）。
var enhanceCount atomic.Int64

// CountEnhanced 累计增强次数（只增不减，进程生命周期内有效）。
func CountEnhanced() int64 { return enhanceCount.Load() }
