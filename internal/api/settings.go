package api

import (
	"encoding/json"
	"net/http"
	"strings"

	"chatgpt2api/internal/config"
	"chatgpt2api/internal/filter"
	"chatgpt2api/internal/settings"

	"github.com/gin-gonic/gin"
)

// settingsKeyWhitelist 允许从 settings.json 回写到 config.Config 的顶层键。
// 只放行"服务端行为参数"，凭证类（auth_key / backup / ai_review 等）与
// 运行期编排参数（本进程创建后不重读的字段）保留在 settings.json 中，不参与覆盖，
// 避免保存后出现"看起来改了但实际没生效"的假象。
var settingsKeyWhitelist = map[string]bool{
	"proxy":                          true,
	"base_url":                       true,
	"image_retention_days":           true,
	"refresh_account_interval_minute": true,
}

// SettingsHandler 控制台「系统设置」读写。
// 存储为 <DataDir>/settings.json，与前端 settingsApi 的报文形状一致（顶层扁平键 + 嵌套段）。
type SettingsHandler struct {
	Store *settings.Store
}

func (h *SettingsHandler) Register(r *gin.RouterGroup) {
	r.GET("/settings", h.Get)
	r.POST("/settings", h.Save)
	r.GET("/third-party-apps", h.GetThirdPartyApps)
}

// Get 返回当前设置。首次访问时以启动配置快照做一次播种，
// 保证前端拿到的不是空对象（否则表单会被 normalizeSettings 回填成全默认值）。
func (h *SettingsHandler) Get(c *gin.Context) {
	data := h.Store.Snapshot()
	if len(data) == 0 {
		data = seedFromConfig(config.Get())
		// 播种失败不阻塞读取，仅不落盘
		_ = h.Store.Save(data)
	}
	c.JSON(http.StatusOK, gin.H{"config": data})
}

// Save 整体保存设置：校验形状 → 落盘 → 热应用可热更的项。
func (h *SettingsHandler) Save(c *gin.Context) {
	var body map[string]any
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{
			"message": "设置报文不是合法的 JSON 对象: " + err.Error(),
			"type":    "invalid_request_error",
		}})
		return
	}
	if body == nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{
			"message": "设置报文不能为空",
			"type":    "invalid_request_error",
		}})
		return
	}
	if err := h.Store.Save(body); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{
			"message": "设置落盘失败: " + err.Error(),
			"type":    "server_error",
		}})
		return
	}
	applied := applyRuntime(body)
	c.JSON(http.StatusOK, gin.H{
		"config":           h.Store.Snapshot(),
		"applied":          applied,
		"restart_required": true,
	})
}

// GetThirdPartyApps 第三方入口设置（顶部导航的无限画布入口按需读取）。
func (h *SettingsHandler) GetThirdPartyApps(c *gin.Context) {
	data := h.Store.Snapshot()
	if len(data) == 0 {
		data = seedFromConfig(config.Get())
	}
	apps, _ := data["third_party_apps"].(map[string]any)
	c.JSON(http.StatusOK, gin.H{"third_party_apps": apps})
}

// applyRuntime 把可热更的设置推给运行时组件，返回已生效的键名。
// 未列入的键仅落盘，重启后由 config.Load 合并生效。
func applyRuntime(data map[string]any) []string {
	applied := make([]string, 0, 4)
	patch := map[string]any{}

	// 敏感词：filter 支持运行时替换（对等 config.Load 中的 filter.SetCustomWords）
	// 所有热更统一收集到 patch，最后一次性写入，避免多次热更互相覆盖。
	if words, ok := toStringSlice(data["sensitive_words"]); ok {
		filter.SetCustomWords(words)
		patch["sensitive_words"] = words
		applied = append(applied, "sensitive_words")
	}
	// 全局代理：后续新建的 backend 连接会读取新值
	if proxy, ok := data["proxy"].(string); ok {
		patch["proxy"] = strings.TrimSpace(proxy)
		applied = append(applied, "proxy")
	}
	if proxyRuntime, ok := data["proxy_runtime"].(map[string]any); ok {
		patch["proxy_runtime"] = proxyRuntime
		applied = append(applied, "proxy_runtime")
	}
	config.ApplyRuntime(patch)
	return applied
}

func toStringSlice(value any) ([]string, bool) {
	items, ok := value.([]any)
	if !ok {
		return nil, false
	}
	out := make([]string, 0, len(items))
	for _, item := range items {
		if s, ok := item.(string); ok {
			out = append(out, s)
		}
	}
	return out, true
}

// seedFromConfig 用启动配置构造首次读取的默认设置。
func seedFromConfig(cfg *config.Config) settings.Data {
	if cfg == nil {
		return settings.Data{}
	}
	return settings.Data{
		"proxy":                           cfg.Proxy,
		"base_url":                        cfg.BaseURL,
		"image_retention_days":            cfg.ImageRetentionDays,
		"refresh_account_interval_minute": cfg.RefreshAccountMin,
		"sensitive_words":                 cfg.SensitiveWords,
		"global_system_prompt":            cfg.GlobalSystemPrompt,
		"image_generation": map[string]any{
			"enabled":          cfg.ImageGeneration.Enabled,
			"supported_models": cfg.ImageGeneration.SupportedModels,
			"output_format":    cfg.ImageGeneration.OutputFormat,
		},
		"image_storage": map[string]any{
			"enabled":          cfg.ImageStorage.Enabled,
			"mode":             cfg.ImageStorage.Mode,
			"webdav_url":       cfg.ImageStorage.WebDAVURL,
			"webdav_username":  cfg.ImageStorage.WebDAVUser,
			"webdav_password":  "",
			"webdav_root_path": cfg.ImageStorage.WebDAVRoot,
			"public_base_url":  cfg.ImageStorage.PublicBaseURL,
		},
		"proxy_runtime": map[string]any{
			"enabled":                  cfg.ProxyRuntime.Enabled,
			"egress_mode":              cfg.ProxyRuntime.EgressMode,
			"proxy_url":                cfg.ProxyRuntime.ProxyURL,
			"resource_proxy_url":       cfg.ProxyRuntime.ResourceProxyURL,
			"skip_ssl_verify":          cfg.ProxyRuntime.SkipSSLVerify,
			"reset_session_status_codes": cfg.ProxyRuntime.ResetSessionStatus,
			"clearance": map[string]any{
				"enabled":          cfg.Clearance.Enabled,
				"mode":             cfg.Clearance.Mode,
				"cf_cookies":       "",
				"cf_clearance":     "",
				"has_cf_cookies":   cfg.Clearance.CfCookies != "",
				"has_cf_clearance": cfg.Clearance.CfClearance != "",
				"user_agent":       cfg.Clearance.UserAgent,
				"browser":          cfg.Clearance.Browser,
				"flaresolverr_url": cfg.Clearance.FlaresolverrURL,
				"timeout_sec":      cfg.Clearance.TimeoutSec,
				"refresh_interval": cfg.Clearance.RefreshInterval,
				"warm_up_on_start": cfg.Clearance.WarmUpOnStart,
			},
		},
	}
}

// 编译期断言：seedFromConfig 产物必须是合法 JSON（防止手改结构后静默产出坏值）。
var _ = func() bool {
	if _, err := json.Marshal(seedFromConfig(config.Get())); err != nil {
		panic("settings seed is not JSON serializable: " + err.Error())
	}
	return true
}()
