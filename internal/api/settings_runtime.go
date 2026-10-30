package api

import (
	"net/http"

	"chatgpt2api/internal/egress"
	"chatgpt2api/internal/scheduler"
	"chatgpt2api/internal/settings"

	"github.com/gin-gonic/gin"
)

// SettingsHandler 系统设置读写。只处理当前 Go 版已有的运行参数；
// 不引入已删除的超分等历史模块。
type SettingsHandler struct {
	Store  *settings.Store
	Sched  *scheduler.Scheduler
	Egress *egress.Service
}

func (h *SettingsHandler) Register(r *gin.RouterGroup) {
	r.GET("/settings", h.Get)
	r.POST("/settings", h.Save)
	r.GET("/third-party-apps", h.GetThirdPartyApps)
	r.GET("/egress", h.GetEgress)
	r.POST("/egress", h.SetEgress)
}

func (h *SettingsHandler) Get(c *gin.Context) {
	data := h.Store.Snapshot()
	if data == nil {
		data = settings.Data{}
	}
	c.JSON(http.StatusOK, gin.H{"config": data, "egress": h.egressView()})
}

func (h *SettingsHandler) Save(c *gin.Context) {
	var body map[string]any
	if err := c.ShouldBindJSON(&body); err != nil || body == nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "设置报文不是合法的 JSON 对象"})
		return
	}
	if err := h.Store.Save(body); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	applied := []string{}
	if v, ok := body["auto_remove_invalid_accounts"].(bool); ok && h.Sched != nil {
		h.Sched.SetAutoRemoveInvalid(v)
		applied = append(applied, "auto_remove_invalid_accounts")
	}
	// 「按账号分配出口 IP」开关热更
	if v, ok := body["egress_enabled"].(bool); ok && h.Egress != nil {
		h.Egress.SetEnabled(v)
		if v {
			h.Egress.Reset()
		}
		applied = append(applied, "egress_enabled")
	}
	c.JSON(http.StatusOK, gin.H{
		"config":  h.Store.Snapshot(),
		"applied": applied,
		"egress":  h.egressView(),
	})
}

// GetEgress 出口分配状态。
func (h *SettingsHandler) GetEgress(c *gin.Context) {
	c.JSON(http.StatusOK, h.egressView())
}

// SetEgress 单独开关出口分配。
func (h *SettingsHandler) SetEgress(c *gin.Context) {
	var body struct {
		Enabled *bool `json:"enabled"`
	}
	if err := c.ShouldBindJSON(&body); err != nil || body.Enabled == nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "enabled required"})
		return
	}
	if h.Egress != nil {
		h.Egress.SetEnabled(*body.Enabled)
		if *body.Enabled {
			h.Egress.Reset()
		}
	}
	c.JSON(http.StatusOK, h.egressView())
}

func (h *SettingsHandler) egressView() gin.H {
	if h.Egress == nil {
		return gin.H{"enabled": false, "configured": false}
	}
	return gin.H{
		"enabled":    h.Egress.Enabled(),
		"configured": h.Egress.Configured(),
	}
}

func (h *SettingsHandler) GetThirdPartyApps(c *gin.Context) {
	data := h.Store.Snapshot()
	apps, _ := data["third_party_apps"].(map[string]any)
	c.JSON(http.StatusOK, gin.H{"third_party_apps": apps})
}
