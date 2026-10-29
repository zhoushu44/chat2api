package api

import (
	"net/http"

	"chatgpt2api/internal/scheduler"
	"chatgpt2api/internal/settings"

	"github.com/gin-gonic/gin"
)

// SettingsHandler 系统设置读写。只处理当前 Go 版已有的运行参数；
// 不引入已删除的超分等历史模块。
type SettingsHandler struct {
	Store *settings.Store
	Sched *scheduler.Scheduler
}

func (h *SettingsHandler) Register(r *gin.RouterGroup) {
	r.GET("/settings", h.Get)
	r.POST("/settings", h.Save)
	r.GET("/third-party-apps", h.GetThirdPartyApps)
}

func (h *SettingsHandler) Get(c *gin.Context) {
	data := h.Store.Snapshot()
	if data == nil {
		data = settings.Data{}
	}
	c.JSON(http.StatusOK, gin.H{"config": data})
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
	c.JSON(http.StatusOK, gin.H{
		"config":  h.Store.Snapshot(),
		"applied": applied,
	})
}

func (h *SettingsHandler) GetThirdPartyApps(c *gin.Context) {
	data := h.Store.Snapshot()
	apps, _ := data["third_party_apps"].(map[string]any)
	c.JSON(http.StatusOK, gin.H{"third_party_apps": apps})
}
