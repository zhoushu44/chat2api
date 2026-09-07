// Package config 负责加载与热更新配置。
// 语义对等 Python 版 services/config.py，但性能相关默认值按 10s 目标重设：
//
//	Python 版                          → Go 版
//	image_poll_initial_wait_secs = 10  → 0.3   （事件驱动，放弃盲等）
//	image_poll_interval_secs     = 10  → 1.0   （自适应轮询起点）
//	image_settle_secs            = 5   → 1.0   （file_ids 连续一致即返回）
package config

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strconv"
	"sync"
	"sync/atomic"
	"time"
)

var (
	globalConfig atomic.Value // *Config 无锁热读
	jsonPool     = sync.Pool{New: func() any { return &bytes.Buffer{} }}
)

// PollConfig 生图轮询性能参数（10s 预算的直接落地点）。
type PollConfig struct {
	// InitialWaitSecs SSE 终止标记出现后的首次轮询延迟。
	// Python 版默认 10s 盲等；Go 版立即轮询（300ms），429 按 Retry-After 退避。
	InitialWaitSecs float64 `json:"image_poll_initial_wait_secs"`
	// IntervalSecs 轮询起始间隔，自适应递增（1→2→3，封顶 MaxIntervalSecs）。
	IntervalSecs float64 `json:"image_poll_interval_secs"`
	// MaxIntervalSecs 轮询间隔封顶。
	MaxIntervalSecs float64 `json:"image_poll_max_interval_secs"`
	// TimeoutSecs 轮询总预算（对等 Python image_poll_timeout_secs，默认 60）。
	TimeoutSecs float64 `json:"image_poll_timeout_secs"`
	// StreamTimeoutSecs SSE 流超时（对等 Python image_stream_timeout_secs，默认 80）。
	StreamTimeoutSecs float64 `json:"image_stream_timeout_secs"`
	// SettleSecs file_ids 稳定确认窗口（Python 默认 5s → 1s）。
	SettleSecs float64 `json:"image_settle_secs"`
	// SettleEnabled 是否启用稳定确认。
	SettleEnabled bool `json:"image_settle_enabled"`
}

// AccountConfig 号池调度参数。
type AccountConfig struct {
	// Concurrency 单账号并发上限（对等 image_account_concurrency，默认 1）。
	Concurrency int `json:"image_account_concurrency"`
	// RetryEnabled 失败换号重试（对等 image_account_retry_enabled）。
	RetryEnabled bool `json:"image_account_retry_enabled"`
	// MaxAttempts 单图最多尝试账号数（对等 image_max_account_attempts，默认 3）。
	MaxAttempts int `json:"image_max_account_attempts"`
	// PreflightTokenRefresh 关键路径 token 预刷新（Go 版新增，默认开）。
	PreflightTokenRefresh bool `json:"image_preflight_token_refresh_enabled"`
	// TokenRefreshLeadSecs token 到期前多少秒后台刷新（Go 版默认 300）。
	TokenRefreshLeadSecs int `json:"token_refresh_lead_secs"`
}

// SchedulerConfig 对齐 abai DAILY_401_CHECK_*
type SchedulerConfig struct {
	Enabled     bool   `json:"daily_401_enabled"`     // DAILY_401_CHECK_ENABLED
	Hour        int    `json:"daily_401_hour"`        // DAILY_401_CHECK_HOUR
	Concurrency int    `json:"daily_401_concurrency"` // DAILY_401_CHECK_CONCURRENCY
	Timezone    string `json:"daily_401_timezone"`    // DAILY_401_CHECK_TIMEZONE
}

// ProxyRuntimeConfig 出站代理运行时（对等 proxy_runtime；Go 版 backend tls-client 透传 proxy_url）。
type ProxyRuntimeConfig struct {
	Enabled            bool     `json:"enabled"`
	EgressMode         string   `json:"egress_mode"` // direct | proxy
	ProxyURL           string   `json:"proxy_url"`
	ResourceProxyURL   string   `json:"resource_proxy_url"`
	SkipSSLVerify      bool     `json:"skip_ssl_verify"`
	ResetSessionStatus []int    `json:"reset_session_status_codes"`
}

// ClearanceConfig CF 验证配置（存储透传，真实 clearance 刷新未实现，见 TASKS.md）。
type ClearanceConfig struct {
	Enabled         bool   `json:"enabled"`
	Mode            string `json:"mode"`
	CfCookies       string `json:"cf_cookies"`
	CfClearance     string `json:"cf_clearance"`
	UserAgent       string `json:"user_agent"`
	Browser         string `json:"browser"`
	FlaresolverrURL string `json:"flaresolverr_url"`
	TimeoutSec      int    `json:"timeout_sec"`
	RefreshInterval int    `json:"refresh_interval"`
	WarmUpOnStart   bool   `json:"warm_up_on_start"`
}

// ImageStorageConfig 图片存储（对等 image_storage；mode=local|webdav|both，Go 版 WebDAV 真实可用）。
type ImageStorageConfig struct {
	Enabled       bool   `json:"enabled"`
	Mode          string `json:"mode"`
	WebDAVURL     string `json:"webdav_url"`
	WebDAVUser    string `json:"webdav_username"`
	WebDAVPass    string `json:"webdav_password"`
	WebDAVRoot    string `json:"webdav_root_path"`
	PublicBaseURL string `json:"public_base_url"`
}

// ChatCompletionCacheConfig 对话缓存 normalize 开关（对等 chat_completion_cache 部分键）。
type ChatCompletionCacheConfig struct {
	Enabled               bool `json:"enabled"`
	NormalizeMessages     bool `json:"normalize_messages"`
	DropAdjacentDuplicates bool `json:"drop_adjacent_duplicates"`
	DropAssistantHistory  bool `json:"drop_assistant_history"`
}

// AIReviewConfig AI 审核链路（对等 ai_review；调用未实现，配置透传）。
type AIReviewConfig struct {
	Enabled bool   `json:"enabled"`
	BaseURL string `json:"base_url"`
	APIKey  string `json:"api_key"`
	Model   string `json:"model"`
	Prompt  string `json:"prompt"`
}

// BackupConfig 备份计划（对等 backup 部分键；执行器未实现，配置透传）。
type BackupConfig struct {
	Enabled         bool   `json:"enabled"`
	IntervalMinutes int    `json:"interval_minutes"`
	RotationKeep    int    `json:"rotation_keep"`
	Prefix          string `json:"prefix"`
}

// ImageGenerationConfig 生图总开关与模型白名单（对等 image_generation 部分键）。
type ImageGenerationConfig struct {
	Enabled          bool     `json:"enabled"`
	SupportedModels  []string `json:"supported_models"`
	OutputFormat     string   `json:"output_format"` // b64_json | url
	explicit         bool     // JSON 中出现过该段（区分"显式禁用"与"零值未配置"）
}

// UnmarshalJSON 记录段落出现（门控只对显式 enabled=false 生效）。
func (c *ImageGenerationConfig) UnmarshalJSON(data []byte) error {
	type alias ImageGenerationConfig
	c.explicit = true
	return json.Unmarshal(data, (*alias)(c))
}

// ExplicitlyDisabled 显式禁用（未配置/零值 Config 视为启用，避免误伤）。
func (c *ImageGenerationConfig) ExplicitlyDisabled() bool {
	return c != nil && c.explicit && !c.Enabled
}

// QuotaLimitsConfig 配额上限（对等 quota_limits；-1 不限；强制执行未实现，配置透传）。
type QuotaLimitsConfig struct {
	Enabled           bool `json:"enabled"`
	FastDailyLimit    int  `json:"fast_daily_limit"`
	ThinkingDailyLimit int `json:"thinking_daily_limit"`
	ProDailyLimit     int  `json:"pro_daily_limit"`
	ImageDailyLimit   int  `json:"image_daily_limit"`
	MusicDailyLimit   int  `json:"music_daily_limit"`
	VideoDailyLimit   int  `json:"video_daily_limit"`
}

// Config 全局配置。字段名与 Python 版 config.json 键名保持一致，方便直接迁移。
type Config struct {
	mu   sync.RWMutex
	data map[string]any

	AuthKey     string `json:"auth-key"`
	StorageType string `json:"storage_backend"` // json | sqlite | postgres | git
	DataDir     string `json:"data_dir"`

	// P2.7 顶层标量（键名与 Python 完全一致）
	Proxy              string   `json:"proxy"`
	FallbackProxy      string   `json:"fallback_proxy"`
	BaseURL            string   `json:"base_url"`
	SensitiveWords     []string `json:"sensitive_words"`
	GlobalSystemPrompt string   `json:"global_system_prompt"`
	RefreshAccountMin  int      `json:"refresh_account_interval_minute"`
	ImageRetentionDays int      `json:"image_retention_days"`
	LogRetentionDays   int      `json:"log_retention_days"`
	ImageMinFreeMB     int      `json:"image_min_free_mb"`

	Poll      PollConfig      `json:"poll"`
	Account   AccountConfig   `json:"account"`
	Scheduler SchedulerConfig `json:"scheduler"`

	// P2.7 嵌套段
	ProxyRuntime        ProxyRuntimeConfig        `json:"proxy_runtime"`
	Clearance           ClearanceConfig           `json:"clearance"`
	ImageStorage        ImageStorageConfig        `json:"image_storage"`
	ChatCompletionCache ChatCompletionCacheConfig `json:"chat_completion_cache"`
	AIReview            AIReviewConfig            `json:"ai_review"`
	Backup              BackupConfig              `json:"backup"`
	ImageGeneration     ImageGenerationConfig     `json:"image_generation"`
	QuotaLimits         QuotaLimitsConfig         `json:"quota_limits"`
}

func defaults() *Config {
	return &Config{
		AuthKey:     "",
		StorageType: "json",
		DataDir:     "./data",
		Poll: PollConfig{
			InitialWaitSecs:  0.3,
			IntervalSecs:     1.0,
			MaxIntervalSecs:  5.0,
			TimeoutSecs:      60.0,
			StreamTimeoutSecs: 80.0,
			SettleSecs:       1.0,
			SettleEnabled:    true,
		},
		Account: AccountConfig{
			Concurrency:           1,
			RetryEnabled:          true,
			MaxAttempts:           3,
			PreflightTokenRefresh: true,
			TokenRefreshLeadSecs:  300,
		},
		Scheduler: SchedulerConfig{
			Enabled:     true,
			Hour:        3,
			Concurrency: 100,
			Timezone:    "Asia/Shanghai",
		},
		RefreshAccountMin:  5,
		ImageRetentionDays: 15,
		LogRetentionDays:   30,
		ImageMinFreeMB:     500,
		ProxyRuntime: ProxyRuntimeConfig{
			EgressMode:         "direct",
			ResetSessionStatus: []int{403},
		},
		Clearance: ClearanceConfig{
			Mode:       "none",
			UserAgent:  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
			Browser:    "chrome",
			TimeoutSec: 60,
		},
		ImageStorage: ImageStorageConfig{
			Mode:       "local",
			WebDAVRoot: "chatgpt2api/images",
		},
		ChatCompletionCache: ChatCompletionCacheConfig{
			Enabled:                true,
			NormalizeMessages:      true,
			DropAdjacentDuplicates: true,
		},
		ImageGeneration: ImageGenerationConfig{
			Enabled:      true,
			OutputFormat: "b64_json",
		},
		QuotaLimits: QuotaLimitsConfig{
			Enabled:            true,
			FastDailyLimit:     -1,
			ThinkingDailyLimit: -1,
			ProDailyLimit:      -1,
			ImageDailyLimit:    -1,
			MusicDailyLimit:    -1,
			VideoDailyLimit:    -1,
		},
	}
}

// EffectiveProxy 出站代理 URL（proxy_runtime 优先于顶层 proxy，对等代理优先级语义简化版）。
func (c *Config) EffectiveProxy() string {
	if c == nil {
		return ""
	}
	if c.ProxyRuntime.Enabled && c.ProxyRuntime.ProxyURL != "" {
		return c.ProxyRuntime.ProxyURL
	}
	return c.Proxy
}

// Load 从 config.json / 环境变量加载配置（CHATGPT2API_AUTH_KEY、STORAGE_BACKEND 覆盖）。
// 深度优化：复用 bytes.Buffer 池 + atomic 热读 + 异步热更新
func Load(path string) (*Config, error) {
	cfg := defaults()
	raw, err := os.ReadFile(path)
	switch {
	case err == nil:
		// 池化解码：复用 Buffer 避免每次分配
		buf := jsonPool.Get().(*bytes.Buffer)
		buf.Reset()
		buf.Write(raw)
		dec := json.NewDecoder(buf)
		if err := dec.Decode(cfg); err != nil {
			jsonPool.Put(buf)
			return nil, err
		}
		jsonPool.Put(buf)
	case os.IsNotExist(err):
		// 纯默认值启动
	default:
		return nil, err
	}
	if v := os.Getenv("CHATGPT2API_AUTH_KEY"); v != "" {
		cfg.AuthKey = v
	}
	if v := os.Getenv("STORAGE_BACKEND"); v != "" {
		cfg.StorageType = v
	}
	if v := os.Getenv("CHATGPT2API_DATA_DIR"); v != "" {
		cfg.DataDir = v
	}
	if cfg.DataDir == "" {
		cfg.DataDir = "./data"
	}
	// Scheduler env overrides 对齐 abai .env.example
	if v := os.Getenv("DAILY_401_CHECK_ENABLED"); v != "" {
		cfg.Scheduler.Enabled = v != "0" && v != "false" && v != "no" && v != "off"
	}
	if v := os.Getenv("DAILY_401_CHECK_HOUR"); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			cfg.Scheduler.Hour = n
		}
	}
	if v := os.Getenv("DAILY_401_CHECK_CONCURRENCY"); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			cfg.Scheduler.Concurrency = n
		}
	}
	if v := os.Getenv("DAILY_401_CHECK_TIMEZONE"); v != "" {
		cfg.Scheduler.Timezone = v
	}
	globalConfig.Store(cfg)
	// 异步热更新：500ms 轮询 mtime，debounce 100ms
	if path != "" {
		go watchConfig(path)
	}
	return cfg, nil
}

// Get 无锁读取当前配置（热路径）
func Get() *Config {
	if v := globalConfig.Load(); v != nil {
		return v.(*Config)
	}
	return defaults()
}

var watchOnce sync.Once

func watchConfig(path string) {
	watchOnce.Do(func() {
		ticker := time.NewTicker(500 * time.Millisecond)
		defer ticker.Stop()
		var lastMod time.Time
		if info, err := os.Stat(path); err == nil {
			lastMod = info.ModTime()
		}
		for range ticker.C {
			info, err := os.Stat(path)
			if err != nil {
				continue
			}
			if info.ModTime().After(lastMod) {
				lastMod = info.ModTime()
				// debounce 100ms
				time.Sleep(100 * time.Millisecond)
				if _, err := Load(path); err == nil {
					// 已热更新
				}
			}
		}
	})
}

// DataPath 返回数据目录下的文件路径。
func (c *Config) DataPath(rel ...string) string {
	return filepath.Join(append([]string{c.DataDir}, rel...)...)
}

// Int 环境变量辅助。
func Int(key string, fallback int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return fallback
}
