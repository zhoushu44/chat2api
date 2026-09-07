package api

import (
	"encoding/json"
	"net/http"
	"time"

	"chatgpt2api/internal/register"

	"github.com/gin-gonic/gin"
)

// 对等 api/register.py + services/register_service.py（自动注册开关）
//
// 鉴权对等 Python（全路由 require_admin）：兼容旧路径与 events SSE 保持开放，
// 面板 /api/register* 由 RegisterRegisterAdmin 挂到 adminAuth 组。
func RegisterRegister(r *gin.RouterGroup, svc *register.Service) {
	// 兼容旧路径
	r.POST("/register", func(c *gin.Context) {
		var body struct {
			Email string `json:"email"`
		}
		_ = c.ShouldBindJSON(&body)
		t := svc.Create(body.Email)
		c.JSON(http.StatusOK, t)
	})
	r.GET("/register/:id", func(c *gin.Context) {
		if t, ok := svc.Get(c.Param("id")); ok {
			c.JSON(http.StatusOK, t)
			return
		}
		c.JSON(http.StatusNotFound, gin.H{"error": "not found"})
	})
	r.GET("/api/register/events", func(c *gin.Context) {
		// SSE 对等 Python /api/register/events（保持开放，浏览器 EventSource 无法带 header）
		c.Header("Content-Type", "text/event-stream")
		c.Header("Cache-Control", "no-cache")
		c.Header("Connection", "keep-alive")
		c.Status(http.StatusOK)
		flusher, ok := c.Writer.(http.Flusher)
		if !ok {
			return
		}
		last := ""
		for i := 0; i < 120; i++ { // 最多 60s，客户端会重连
			cfg := svc.GetConfig()
			b, _ := json.Marshal(cfg)
			payload := string(b)
			if payload != last {
				last = payload
				_, _ = c.Writer.Write([]byte("data: " + payload + "\n\n"))
				flusher.Flush()
			}
			select {
			case <-c.Request.Context().Done():
				return
			case <-time.After(500 * time.Millisecond):
			}
		}
	})
	_ = http.StatusOK
}

// RegisterRegisterAdmin 面板 /api/register*（调用方须传入已加 adminAuth 的组，对等 require_admin）。
func RegisterRegisterAdmin(api *gin.RouterGroup, svc *register.Service) {
	api.GET("", func(c *gin.Context) {
		cfg := svc.GetConfig()
		c.JSON(http.StatusOK, gin.H{"register": cfg})
	})
	api.POST("", func(c *gin.Context) {
		var updates map[string]any
		_ = c.ShouldBindJSON(&updates)
		// 兼容前端直接传 Config 扁平结构或 {register: {...}}
		if v, ok := updates["register"]; ok {
			if m, ok := v.(map[string]any); ok {
				updates = m
			}
		}
		// 允许 auto_refill / auto_refill_interval 等任务参数
		cfg := svc.Update(updates)
		c.JSON(http.StatusOK, gin.H{"register": cfg})
	})
	api.POST("/start", func(c *gin.Context) {
		cfg := svc.Start()
		c.JSON(http.StatusOK, gin.H{"register": cfg})
	})
	api.POST("/stop", func(c *gin.Context) {
		cfg := svc.Stop()
		c.JSON(http.StatusOK, gin.H{"register": cfg})
	})
	api.POST("/reset", func(c *gin.Context) {
		cfg := svc.Reset()
		c.JSON(http.StatusOK, gin.H{"register": cfg})
	})
	api.POST("/outlook-pool/reset", func(c *gin.Context) {
		var body struct {
			Scope string `json:"scope"`
		}
		_ = c.ShouldBindJSON(&body)
		// 已由 RegiForge 邮箱通道取代，直接返回当前配置
		svc.AppendLog("Outlook 邮箱池已由 RegiForge 邮箱通道取代，无需维护", "yellow")
		cfg := svc.GetConfig()
		c.JSON(http.StatusOK, gin.H{"register": cfg})
	})
	api.POST("/gptmail/status", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"status": gin.H{"status": "disabled", "message": "gptmail 已由 RegiForge 任务模式取代"}})
	})
	api.POST("/gptmail/refresh-key", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"status": gin.H{"status": "disabled", "message": "gptmail 已由 RegiForge 任务模式取代"}})
	})
}
