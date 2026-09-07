// Package backend 是 ChatGPT 官网逆向核心。
// 对等 Python services/openai_backend_api.py（3,327 行），
// HTTP 层使用 bogdanfinn/tls-client 实现 TLS 指纹伪装（curl_cffi 等价物）。
package backend

import (
	"context"
	"net/http"
	"sync"
	"time"

	"chatgpt2api/internal/sse"

	fhttp "github.com/bogdanfinn/fhttp"
	tls_client "github.com/bogdanfinn/tls-client"
	"github.com/bogdanfinn/tls-client/profiles"
)

// httpDoer 最小 HTTP 抽象，便于测试注入（真实实现为 tls-client）。
type httpDoer interface {
	Do(req *fhttp.Request) (*fhttp.Response, error)
}

// Backend 单账号会话客户端（对等 Python OpenAIBackendAPI）。
type Backend struct {
	BaseURL           string
	AccessToken       string
	clientVersion     string
	clientBuildNumber string
	fp                Fingerprint
	http              httpDoer
	// scriptSources/dataBuild 由 Bootstrap 预热解析（PoW p_token 生成所需）。
	scriptSources []string
	dataBuild     string
	// bootstrapAt 上次预热成功时刻：首页 HTML 很少变化，10 分钟内复用省 ~2s/图。
	mu          sync.Mutex
	bootstrapAt time.Time
}

// NewBackend 创建后端客户端：指纹按账号覆盖合并（对等 __init__:207-281）。
func NewBackend(accessToken string, fpOverride map[string]string, proxy string) (*Backend, error) {
	httpClient, err := NewClient(profiles.Chrome_110, proxy)
	if err != nil {
		return nil, err
	}
	return &Backend{
		BaseURL:           "https://chatgpt.com",
		AccessToken:       accessToken,
		clientVersion:     DefaultClientVersion,
		clientBuildNumber: DefaultClientBuildNumber,
		fp:                DefaultFingerprint().Merge(fpOverride),
		http:              httpClient,
	}, nil
}

// NewClient 创建带指定指纹 profile 的 HTTP 客户端（对等 impersonate 参数）。
func NewClient(profile profiles.ClientProfile, proxy string) (tls_client.HttpClient, error) {
	opts := []tls_client.HttpClientOption{
		tls_client.WithTimeoutSeconds(120),
		tls_client.WithClientProfile(profile),
		tls_client.WithNotFollowRedirects(),
		tls_client.WithCookieJar(tls_client.NewCookieJar()),
	}
	if proxy != "" {
		opts = append(opts, tls_client.WithProxyUrl(proxy))
	}
	return tls_client.NewHttpClient(tls_client.NewNoopLogger(), opts...)
}

// StageTiming 生图各阶段耗时（对等 Python _image_result_timing，验证 10s 预算的度量）。
type StageTiming struct {
	AccountPickMs  int64 `json:"account_pick_ms"`
	BootstrapMs    int64 `json:"bootstrap_ms"`
	RequirementsMs int64 `json:"requirements_ms"`
	PrepareMs      int64 `json:"prepare_ms"`
	SSEStreamMs    int64 `json:"sse_stream_ms"`
	InitialWaitMs  int64 `json:"initial_wait_ms"`
	PollWaitMs     int64 `json:"poll_wait_ms"`
	PollCount      int   `json:"poll_count"`
	ResolveMs      int64 `json:"resolve_ms"`
	DownloadMs     int64 `json:"download_ms"`
	EncodeMs       int64 `json:"encode_ms"`
	TotalMs        int64 `json:"total_ms"`
}

// ImageResult 生图结果。
type ImageResult struct {
	FileIDs      []string
	SedimentIDs  []string
	ConversationID string // poll/resolve 所需的会话 ID
	Bytes        [][]byte // 已下载图片（b64 模式）
	URLs         []string // URL 模式
	Stage        StageTiming
}

// PollPolicy 轮询策略（由 config.PollConfig 驱动，10s 预算核心）。
type PollPolicy struct {
	InitialWait   time.Duration // Python 默认 10s → Go 默认 300ms
	Interval      time.Duration // 起始 1s
	MaxInterval   time.Duration // 封顶 5s
	Timeout       time.Duration
	Settle        time.Duration
	StreamTimeout time.Duration // SSE 流超时
}

// GenerateImageFlow 事件驱动生图主管线（M1 核心实现点）。
//
// 与 Python 版的关键差异（10s 预算的来源）：
//  1. SSE 流内解析 asset pointer 与终止标记，标记出现即离开 SSE 阶段（不等连接关闭）
//  2. InitialWait 默认 300ms 而非 10s；429 按 Retry-After 微退避
//  3. 轮询自适应 1→2→3s（Python 固定 10s）
//  4. file_ids 连续两次一致即返回（Python settle 固定 5s）
//  5. 多图并发下载
func (b *Backend) GenerateImageFlow(ctx context.Context, prompt string, policy PollPolicy) (*ImageResult, error) {
	// 已由 real.go:GenerateImage 实现全链路，此为兼容入口
	return b.GenerateImage(ctx, prompt, "gpt-image-2", nil, policy)
}

// newStdHeaders 官网请求头（对等 Python 版 headers 常量）。
func newStdHeaders(token string) http.Header {
	h := http.Header{}
	h.Set("Authorization", "Bearer "+token)
	h.Set("Accept", "text/event-stream")
	h.Set("Content-Type", "application/json")
	h.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36")
	return h
}

var _ = sse.New // 保持包引用（M1 实装时使用）
var _ = time.Now
