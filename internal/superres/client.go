package superres

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"
	"github.com/tencentyun/cos-go-sdk-v5"
)

// COSClient 腾讯云 COS 客户端（数据万象 AI 超分）。
// 惰性创建 + 按 Config 指纹缓存：配置未变复用同一 client，变更后自动重建。
type COSClient struct {
	mu      sync.Mutex
	cached  *cos.Client
	fpCache string // 构建时使用的配置指纹（bucket+region+secretID）
}

// NewCOSClient 创建客户端容器（不建连，首次调用时惰性初始化）。
func NewCOSClient() *COSClient { return &COSClient{} }

// configFingerprint 配置指纹：三个字段任一变化即重建 client。
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
		// 全球加速等自定义端点：bucket 独立子域形式 cos.accelerate.myqcloud.com
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

// suffixByContentType 按源图 MIME 推断落盘后缀（对等 Python upload_result）。
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

// dateKey 日期分层路径（对等 image-super-resolution/YYYY/MM/DD/）。
func dateKey(t time.Time) string {
	return t.Format("2006/01/02")
}

// UploadAndSuperResolution 上传源图并在上传时触发数据万象 AI 超分（对等 Python
// upload_source_with_super_resolution：put_object + PicOperations ci-process=AISuperResolution&magnify=factor）。
// 返回超分成品的公网 URL。sourceKey 仅为临时源图 key，调用方负责事后删除。
// OutputFormat 非空时，超分完成后对成品追加一步 ImageProcess 云上转码（webp/jpeg），
// 返回转码后对象的 URL（尺寸不变，体积约为无损 PNG 的 1/10~1/20）。
// 注意：转码失败自动降级返回 PNG 原成品（与整体「失败不阻断」语义一致）。
func (s *COSClient) UploadAndSuperResolution(ctx context.Context, cfg *Config, source []byte, contentType string, factor int) (resultURL string, sourceKey string, err error) {
	if factor != 2 && factor != 4 {
		return "", "", fmt.Errorf("superres: factor must be 2 or 4, got %d", factor)
	}
	client, err := s.client(cfg)
	if err != nil {
		return "", "", err
	}
	id := uuid.NewString()
	suffix := suffixByContentType(contentType)
	sourceKey = fmt.Sprintf("image-super-resolution/source/%s%s", id, suffix)
	resultKey := fmt.Sprintf("/image-super-resolution/%s/%s%s", dateKey(time.Now()), uuid.NewString(), suffix)

	opt := &cos.ObjectPutOptions{
		ObjectPutHeaderOptions: &cos.ObjectPutHeaderOptions{
			ContentType:  contentType,
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

	res, _, err := client.CI.Put(ctx, sourceKey, strings.NewReader(string(source)), opt)
	if err != nil {
		return "", "", fmt.Errorf("superres: cos upload+super-resolution failed: %w", err)
	}
	// 校验处理结果（ProcessResults 为空或 Key 缺失视为失败）
	if len(res.ProcessResults) == 0 || res.ProcessResults[0].Key == "" {
		return "", "", fmt.Errorf("superres: cos process returned no result object")
	}

	// 可选输出转码（OutputFormat=webp/jpeg）：对超分成品做云上 ImageProcess。
	// AI 超分不支持管道链（实测 imageMogr2|AISuperResolution 的 magnify 参数被拒），
	// 因此分两步：先超分出 PNG，再对成品 POST ?image_process 持久化转码。
	if f := normalizeOutputFormat(cfg.OutputFormat); f != "" {
		compressedKey := fmt.Sprintf("/image-super-resolution/%s/%s.%s", dateKey(time.Now()), uuid.NewString(), f)
		pic2 := &cos.PicOperations{
			IsPicInfo: 1,
			Rules: []cos.PicOperationsRules{
				{
					FileId: compressedKey,
					Rule:   fmt.Sprintf("imageMogr2/format/%s/quality/%d", f, cfg.outputQuality()),
				},
			},
		}
		res2, _, err2 := client.CI.ImageProcess(ctx, strings.TrimPrefix(resultKey, "/"), pic2)
		// 转码失败降级：返回无损 PNG 成品（可用性优先）
		if err2 == nil && len(res2.ProcessResults) > 0 && res2.ProcessResults[0].Key != "" {
			return cfg.resultURL(compressedKey), sourceKey, nil
		}
		log.Printf("[superres] output transcode to %s failed (fallback to lossless png): %v", f, err2)
	}
	return cfg.resultURL(resultKey), sourceKey, nil
}

// normalizeOutputFormat 归一化输出格式：webp / jpeg 合法（png/空 = 保持无损）。
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

// outputQuality 转码质量（默认 85；范围外收敛到 60~95）。
func (c *Config) outputQuality() int {
	if c.OutputQuality < 60 || c.OutputQuality > 95 {
		return 85
	}
	return c.OutputQuality
}

// DeleteSource 删除上传的临时源图（尽力而为，失败不影响主流程）。
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
