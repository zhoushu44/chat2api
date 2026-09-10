package api

import (
	"net/http"

	"chatgpt2api/internal/provider"

	"github.com/gin-gonic/gin"
)

// ProviderHandler 对齐 abai api/provider_definitions.py + provider_settings.py
type ProviderHandler struct{}

func (h *ProviderHandler) Register(r *gin.RouterGroup) {
	r.GET("/provider_definitions", h.ListDefs)
	r.GET("/provider_definitions/:type", h.ListDefsByType)
	r.GET("/provider_settings", h.ListSettings)
	r.GET("/provider_settings/:type", h.ListSettingsByType)
	r.PUT("/provider_settings/:type/:key", h.UpsertSetting)
	r.POST("/provider_settings/:type/:key/test", h.TestSetting)
}

func (h *ProviderHandler) ListDefs(c *gin.Context) {
	out := map[string]any{
		"mailbox": provider.ListDefinitions(provider.TypeMailbox),
		"proxy":   provider.ListDefinitions(provider.TypeProxy),
		"captcha": provider.ListDefinitions(provider.TypeCaptcha),
	}
	c.JSON(http.StatusOK, gin.H{"data": out})
}

func (h *ProviderHandler) ListDefsByType(c *gin.Context) {
	t := provider.Type(c.Param("type"))
	c.JSON(http.StatusOK, gin.H{"data": provider.ListDefinitions(t)})
}

func (h *ProviderHandler) ListSettings(c *gin.Context) {
	out := map[string]any{
		"mailbox": provider.ListSettings(provider.TypeMailbox),
		"proxy":   provider.ListSettings(provider.TypeProxy),
		"captcha": provider.ListSettings(provider.TypeCaptcha),
	}
	c.JSON(http.StatusOK, gin.H{"data": out})
}

func (h *ProviderHandler) ListSettingsByType(c *gin.Context) {
	t := provider.Type(c.Param("type"))
	c.JSON(http.StatusOK, gin.H{"data": provider.ListSettings(t)})
}

func (h *ProviderHandler) UpsertSetting(c *gin.Context) {
	t := provider.Type(c.Param("type"))
	key := c.Param("key")
	if err := provider.Validate(t, key); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	var body struct {
		Enabled   *bool          `json:"enabled"`
		IsDefault *bool          `json:"is_default"`
		Config    map[string]any `json:"config"`
		Auth      map[string]any `json:"auth"`
		Meta      map[string]any `json:"meta"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	// 读取现有或新建
	exist, _ := provider.GetSetting(t, key)
	s := provider.Setting{Type: t, Key: key, Config: map[string]any{}, Auth: map[string]any{}, Meta: map[string]any{}}
	if exist != nil {
		s = *exist
	}
	if body.Enabled != nil {
		s.Enabled = *body.Enabled
	} else if exist == nil {
		s.Enabled = true
	}
	if body.IsDefault != nil {
		s.IsDefault = *body.IsDefault
	}
	if body.Config != nil {
		s.Config = body.Config
	}
	if body.Auth != nil {
		s.Auth = body.Auth
	}
	if body.Meta != nil {
		s.Meta = body.Meta
	}
	provider.UpsertSetting(s)
	c.JSON(http.StatusOK, gin.H{"ok": true, "data": s})
}

// TestSetting 测试 provider 配置连通性（warp 测代理、mailnest 测 key）
func (h *ProviderHandler) TestSetting(c *gin.Context) {
	t := provider.Type(c.Param("type"))
	key := c.Param("key")
	if err := provider.Validate(t, key); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	var body struct {
		Config map[string]any `json:"config"`
	}
	_ = c.ShouldBindJSON(&body)
	if body.Config == nil {
		body.Config = map[string]any{}
	}
	// 合并已保存配置，body 覆盖（支持先保存后测试，或直接测试）
	if exist, _ := provider.GetSetting(t, key); exist != nil {
		for k, v := range exist.Config {
			if _, ok := body.Config[k]; !ok {
				body.Config[k] = v
			}
		}
	}
	var res testResult
	switch {
	case t == provider.TypeProxy && key == "warp":
		res = testProxyWarp(body.Config)
	case t == provider.TypeMailbox && key == "mailnest":
		res = testMailboxMailnest(body.Config)
	default:
		res = testResult{OK: false, Message: "暂不支持测试此 provider: " + string(t) + "/" + key}
	}
	c.JSON(http.StatusOK, gin.H{"ok": res.OK, "message": res.Message, "detail": res.Detail})
}
