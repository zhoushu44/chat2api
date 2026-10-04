package superres

import (
	"bytes"
	"context"
	"fmt"
	"image"
	"image/jpeg"
	_ "image/png" // 注册 PNG 解码器，供 image.Decode 使用
	"log"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"
	"github.com/tencentyun/cos-go-sdk-v5"
)

// ciPutTimeout 单次超分上传+处理的时间上限。
// 客户端整体 Timeout 是 10 分钟（对齐原 Python 实现），但跨洋链路一旦卡住
// 会拖满 10 分钟才失败，导致请求长时间挂起。这里为单次尝试加独立上限，
// 超时即重试，让最坏耗时可控。
const ciPutTimeout = 90 * time.Second

// ciPut 带独立超时执行一次「上传+超分」调用。
func ciPut(ctx context.Context, client *cos.Client, key string, source []byte, opt *cos.ObjectPutOptions) (*cos.ImageProcessResult, error) {
	callCtx, cancel := context.WithTimeout(ctx, ciPutTimeout)
	defer cancel()
	res, _, err := client.CI.Put(callCtx, key, strings.NewReader(string(source)), opt)
	return res, err
}

// superresRetries 腾讯云 AI 超分失败后的最大重试次数。
// 跨洋链路偶发 TCP 超时（read: connection timed out），单次重试不够。
const superresRetries = 3

// shouldRetrySuperres 判断超分错误是否值得重试。
// 数据万象在并发压力/瞬时限流下会返回 500 InternalError；参数类错误重试无意义。
func shouldRetrySuperres(err error) bool {
	if err == nil {
		return false
	}
	msg := strings.ToLower(err.Error())
	switch {
	case strings.Contains(msg, "internalerror"),
		strings.Contains(msg, "internal error"),
		strings.Contains(msg, "serviceunavailable"),
		strings.Contains(msg, "requesttimeout"),
		strings.Contains(msg, "too many requests"),
		strings.Contains(msg, "timeout"),
		strings.Contains(msg, "timed out"),
		strings.Contains(msg, "connection reset"),
		strings.Contains(msg, "connection refused"),
		strings.Contains(msg, "eof"):
		return true
	}
	return false
}

// toUploadFriendlyJPEG 把源图重编码为 JPEG，用于 4 倍超分档位。
//
// 数据万象 AISuperResolution 的硬限制是「处理后的图与原图均不可超过 32MB」。
// 4 倍超分使成品体积放大约 16 倍：源 PNG 1.5MB → 成品 PNG 20MB+，
// 遇到复杂图（渐变丰富、噪声多）会直接越过 32MB，表现为 500 InternalError。
// 转 JPEG 后源图体积通常降到 1/3~1/10，成品也随之为 JPEG 体积，从而稳定通过。
//
// 返回 (新字节, 新 Content-Type, 是否已转换)。已是 JPEG/WebP 或解码失败时返回 false，
// 由调用方沿用原数据（保证不因重编码失败而中断出图）。
func toUploadFriendlyJPEG(data []byte, contentType string) ([]byte, string, bool) {
	ct := strings.ToLower(contentType)
	if strings.Contains(ct, "jpeg") || strings.Contains(ct, "jpg") || strings.Contains(ct, "webp") {
		return nil, "", false
	}
	img, _, err := image.Decode(bytes.NewReader(data))
	if err != nil {
		return nil, "", false
	}
	var buf bytes.Buffer
	if err := jpeg.Encode(&buf, img, &jpeg.Options{Quality: 95}); err != nil {
		return nil, "", false
	}
	out := buf.Bytes()
	// 极端情况下重编码反而更大（源图本就高度压缩），此时不转换。
	if len(out) >= len(data) {
		return nil, "", false
	}
	return out, "image/jpeg", true
}

// COSClient 腾讯云 COS 客户端（含数据万象 AI 超分）。
// 惰性创建 + 按 Config 指纹缓存：配置未变则复用同一 client，变更后自动重建。
type COSClient struct {
	mu      sync.Mutex
	cached  *cos.Client
	fpCache string // 创建时使用的配置指纹（bucket+region+secretID）。
}

// NewCOSClient 创建客户端；配置惰性，首次调用时再初始化。
func NewCOSClient() *COSClient { return &COSClient{} }

// configFingerprint 配置指纹：任一字段变化则重建 client。
func configFingerprint(cfg *Config) string {
	return cfg.SecretID + "|" + cfg.Bucket + "|" + cfg.Region + "|" + cfg.UploadEndpoint
}

// client 惰性获取（或重建）COS client。
func (c *COSClient) client(cfg *Config) (*cos.Client, error) {
	if c == nil {
		return nil, fmt.Errorf("superres: nil client")
	}
	fp := configFingerprint(cfg)
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.cached != nil && c.fpCache == fp {
		return c.cached, nil
	}
	host := cfg.Bucket + ".cos." + cfg.Region + ".myqcloud.com"
	if cfg.UploadEndpoint != "" {
		// 全球加速的自定义端点：bucket 拼在加速域名前（cos.accelerate.myqcloud.com）
		host = cfg.Bucket + "." + cfg.UploadEndpoint
	}
	u, err := url.Parse("https://" + host)
	if err != nil {
		return nil, fmt.Errorf("superres: invalid cos host %q: %w", host, err)
	}
	client := cos.NewClient(&cos.BaseURL{BucketURL: u}, &http.Client{
		Timeout: 10 * time.Minute, // 对等 Python CosConfig(Timeout=600)
		Transport: &cos.AuthorizationTransport{
			SecretID:  cfg.SecretID,
			SecretKey: cfg.SecretKey,
		},
	})
	c.cached = client
	c.fpCache = fp
	return client, nil
}

// resultURL COS 成品公网地址。
func (c *Config) resultURL(key string) string {
	return strings.TrimSuffix(c.PublicBaseURL, "/") + "/" + strings.TrimPrefix(key, "/")
}

// suffixByContentType 由源图 MIME 推导落盘后缀（对等 Python upload_result）。
func suffixByContentType(contentType string) string {
	ct := strings.ToLower(contentType)
	switch {
	case strings.Contains(ct, "jpeg"), strings.Contains(ct, "jpg"):
		return ".jpg"
	case strings.Contains(ct, "webp"):
		return ".webp"
	default:
		return ".png"
	}
}

// suffixForFormat 由转码格式推导成品后缀；空表示保持源格式。
func suffixForFormat(format, fallback string) string {
	switch format {
	case "webp":
		return ".webp"
	case "jpeg":
		return ".jpg"
	default:
		return fallback
	}
}

// dateKey 日期分层路径（对等 image-super-resolution/YYYY/MM/DD/）。
func dateKey(t time.Time) string {
	return t.Format("2006/01/02")
}

// UploadAndSuperResolution 上传源图，以「上传时处理」触发数据万象 AI 超分，对等 Python
// upload_source_with_super_resolution：put_object + PicOperations
// ci-process=AISuperResolution&magnify=factor。返回成品公网 URL；sourceKey 为临时源图 key，调用方负责后续删除。
//
// 本地改动（真实 2K/4K）：超分产物尺寸是「源图×factor」的近似值（如 1254→5016），
// 与请求尺寸并不相等。当 plan.Exact 为真且未禁用精确尺寸时，这里会追加一次
// 数据万象管道处理 imageMogr2/thumbnail/<W>x<H>!，把成品严格缩放为请求的目标尺寸；
// 若配置了 OutputFormat（webp/jpeg），缩放与转码在同一次调用内完成，只多一次 CI 请求。
//
// 转码失败自动降级为超分原图（PNG），保证「失败不阻塞出图」。
func (s *COSClient) UploadAndSuperResolution(ctx context.Context, cfg *Config, source []byte, contentType string, plan *Plan) (resultURL string, sourceKey string, err error) {
	if plan == nil {
		return "", "", fmt.Errorf("superres: nil plan")
	}
	factor := plan.Factor
	if factor != 2 && factor != 4 {
		return "", "", fmt.Errorf("superres: factor must be 2 or 4, got %d", factor)
	}
	client, err := s.client(cfg)
	if err != nil {
		return "", "", err
	}
	id := uuid.NewString()
	suffix := suffixByContentType(contentType)
	if plan != nil && plan.Factor >= 4 {
		// 4 倍超分会把成品体积放大 ~16 倍。真实 AI 出图是无损 PNG（1~5MB），
		// 4K 成品 PNG 极易突破数据万象「处理后图片不得超过 32MB」的硬限制，
		// 表现为 PUT 返回 500 InternalError。
		// 因此在 4 倍档位先把源图无损转 JPEG（体积降 3~10 倍），
		// 保证超分能稳定执行；最终格式仍由 OutputFormat / 精确缩放决定。
		if converted, newType, ok := toUploadFriendlyJPEG(source, contentType); ok {
			source, contentType, suffix = converted, newType, ".jpg"
			id = uuid.NewString()
		}
	}
	sourceKey = fmt.Sprintf("image-super-resolution/source/%s%s", id, suffix)
	resultKey := fmt.Sprintf("/image-super-resolution/%s/%s%s", dateKey(time.Now()), uuid.NewString(), suffix)

	opt := &cos.ObjectPutOptions{
		ObjectPutHeaderOptions: &cos.ObjectPutHeaderOptions{
			ContentType:   contentType,
			XOptionHeader: &http.Header{},
		},
	}
	pic := &cos.PicOperations{
		IsPicInfo: 1,
		Rules: []cos.PicOperationsRules{
			{
				FileId: resultKey,
				Rule:   fmt.Sprintf("ci-process=AISuperResolution&magnify=%d", factor),
			},
		},
	}
	opt.XOptionHeader.Add("Pic-Operations", cos.EncodePicOperations(pic))

	res, err := ciPut(ctx, client, sourceKey, source, opt)
	if err != nil {
		// 数据万象在并发压力下会偶发 500 InternalError / 限流，
		// 跨洋链路也可能 read: connection timed out；单次失败不必降级为原图，
		// 重试可避免成品尺寸不符（降级会返回未超分的原图）。
		if shouldRetrySuperres(err) {
			for attempt := 1; attempt <= superresRetries; attempt++ {
				time.Sleep(time.Duration(attempt) * 800 * time.Millisecond)
				res, err = ciPut(ctx, client, sourceKey, source, opt)
				if err == nil {
					log.Printf("[superres] retry %d/%d succeeded", attempt, superresRetries)
					break
				}
				log.Printf("[superres] retry %d/%d failed: %v", attempt, superresRetries, err)
			}
		}
		if err != nil {
			return "", sourceKey, fmt.Errorf("superres: cos upload+super-resolution failed: %w", err)
		}
	}
	// 校验处理结果：ProcessResults 为空或 Key 缺失视为失败。
	if len(res.ProcessResults) == 0 || res.ProcessResults[0].Key == "" {
		return "", "", fmt.Errorf("superres: cos process returned no result object")
	}

	// 可选后处理：精确缩放（请求了具体尺寸时）+ 格式转码（OutputFormat 非空时）。
	// 两者合并成一条 imageMogr2 管道，一次 CI 调用完成，失败则回退超分原图。
	format := normalizeOutputFormat(cfg.OutputFormat)
	rule := buildPostProcessRule(plan, cfg, format)
	if rule != "" {
		finalSuffix := suffixForFormat(format, suffix)
		finalKey := fmt.Sprintf("/image-super-resolution/%s/%s%s", dateKey(time.Now()), uuid.NewString(), finalSuffix)
		pic2 := &cos.PicOperations{
			IsPicInfo: 1,
			Rules: []cos.PicOperationsRules{
				{FileId: finalKey, Rule: rule},
			},
		}
		res2, _, err2 := client.CI.ImageProcess(ctx, strings.TrimPrefix(resultKey, "/"), pic2)
		// 与超分同样的瞬时限流重试：后处理失败会退回未精确缩放的超分原图，
		// 尺寸将变成 源图×factor 的近似值，因此值得重试。
		if err2 != nil && shouldRetrySuperres(err2) {
			for attempt := 1; attempt <= superresRetries; attempt++ {
				time.Sleep(time.Duration(attempt) * 800 * time.Millisecond)
				res2, _, err2 = client.CI.ImageProcess(ctx, strings.TrimPrefix(resultKey, "/"), pic2)
				if err2 == nil {
					log.Printf("[superres] post-process retry %d/%d succeeded", attempt, superresRetries)
					break
				}
			}
		}
		if err2 == nil && len(res2.ProcessResults) > 0 && res2.ProcessResults[0].Key != "" {
			return cfg.resultURL(finalKey), sourceKey, nil
		}
		log.Printf("[superres] post-process %q failed (fallback to upscaled original): %v", rule, err2)
	}
	return cfg.resultURL(resultKey), sourceKey, nil
}

// buildPostProcessRule 组装超分之后的后处理管道规则。
//
//	精确缩放：imageMogr2/thumbnail/<W>x<H>!   （! 表示强制到目标尺寸、不保持比例）
//	格式转码：/format/<webp|jpeg>/quality/<60-95>
//
// 返回空字符串表示无需后处理。
func buildPostProcessRule(plan *Plan, cfg *Config, format string) string {
	rule := ""
	if plan != nil && plan.Exact && !cfg.DisableExactSize && plan.Target != nil &&
		plan.Target.W > 0 && plan.Target.H > 0 {
		rule = fmt.Sprintf("imageMogr2/thumbnail/%dx%d!", plan.Target.W, plan.Target.H)
	}
	if format != "" {
		seg := fmt.Sprintf("format/%s/quality/%d", format, cfg.outputQuality())
		if rule == "" {
			rule = "imageMogr2/" + seg
		} else {
			rule += "/" + seg
		}
	}
	return rule
}

// normalizeOutputFormat 归一化输出格式：webp / jpeg 合法；png/空 = 不转码。
func normalizeOutputFormat(s string) string {
	switch strings.ToLower(strings.TrimSpace(s)) {
	case "webp":
		return "webp"
	case "jpeg", "jpg":
		return "jpeg"
	default:
		return ""
	}
}

// outputQuality 转码质量，默认 90（取值范围收敛到 60~95）。
// 90：4K 约 3~4MB，放大后对比原 PNG 无可感差异。
func (c *Config) outputQuality() int {
	if c.OutputQuality < 60 || c.OutputQuality > 95 {
		return 90
	}
	return c.OutputQuality
}

// DeleteSource 删除上传的临时源图；失败不影响主流程。
func (s *COSClient) DeleteSource(ctx context.Context, cfg *Config, sourceKey string) {
	if sourceKey == "" {
		return
	}
	client, err := s.client(cfg)
	if err != nil {
		return
	}
	_, _ = client.Object.Delete(ctx, sourceKey)
}
