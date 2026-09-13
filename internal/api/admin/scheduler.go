package admin

import (
	"net/http"

	"chatgpt2api/internal/scheduler"

	"github.com/gin-gonic/gin"
)

// SchedulerHandler 调度器开关（账号页「每日401验活+协议恢复」开关）。
// 需要注入 running Scheduler + DataDir（持久化开关状态）+ 启动默认值。
type SchedulerHandler struct {
	Sched      *scheduler.Scheduler
	DataDir    string
	DefEnabled bool
}

func (h *SchedulerHandler) Register(r *gin.RouterGroup) {
	r.GET("/scheduler", h.Get)
	r.PUT("/scheduler", h.Set)
}

func (h *SchedulerHandler) Get(c *gin.Context) {
	enabled := h.DefEnabled
	recovery := true
	if h.Sched != nil {
		enabled = h.Sched.Enabled
		recovery = h.Sched.RecoveryEnabled
	}
	hour, conc := 3, 0
	if h.Sched != nil {
		hour, conc = h.Sched.Hour, h.Sched.Concurrency
	}
	c.JSON(http.StatusOK, gin.H{
		"enabled":     enabled,
		"hour":        hour,
		"concurrency": conc,
		"recovery":    recovery,
	})
}

func (h *SchedulerHandler) Set(c *gin.Context) {
	var body struct {
		Enabled  *bool `json:"enabled"`
		Recovery *bool `json:"recovery"`
	}
	if err := c.ShouldBindJSON(&body); err != nil || (body.Enabled == nil && body.Recovery == nil) {
		c.JSON(http.StatusBadRequest, gin.H{"error": "enabled or recovery required"})
		return
	}
	if h.Sched != nil {
		if body.Enabled != nil {
			h.Sched.SetEnabled(*body.Enabled)
		}
		if body.Recovery != nil {
			// 运行时热更即可；持久化按 Enabled 一并落盘（recovery 跟随配置文件默认）
			h.Sched.SetRecoveryEnabled(*body.Recovery)
		}
	}
	if body.Enabled != nil {
		if err := scheduler.SavePersistedEnabled(h.DataDir, *body.Enabled); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}
	}
	c.JSON(http.StatusOK, gin.H{"ok": true})
}
