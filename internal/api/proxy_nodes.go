package api

import (
	"net/http"

	"chatgpt2api/internal/proxy"

	"github.com/gin-gonic/gin"
)

// ProxyHandler 对齐 abai api/proxy_nodes.py
type ProxyHandler struct{}

func (h *ProxyHandler) Register(r *gin.RouterGroup) {
	r.GET("/proxy_nodes", h.List)
	r.POST("/proxy_nodes", h.Add)
	r.POST("/proxy_nodes/check", h.Check)
	r.POST("/proxy_nodes/:url/report_success", h.ReportSuccess)
	r.POST("/proxy_nodes/:url/report_fail", h.ReportFail)
}

func (h *ProxyHandler) List(c *gin.Context) {
	region := c.Query("region")
	// 演示：返回 DefaultPool 的下一个推荐
	next := proxy.DefaultPool.GetNext(region)
	c.JSON(http.StatusOK, gin.H{"next": next, "region": region})
}

func (h *ProxyHandler) Add(c *gin.Context) {
	var body struct {
		URL    string `json:"url" binding:"required"`
		Region string `json:"region"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	if !proxy.IsValid(body.URL) {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid proxy url"})
		return
	}
	proxy.DefaultPool.Add(body.URL, body.Region)
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

func (h *ProxyHandler) Check(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

func (h *ProxyHandler) ReportSuccess(c *gin.Context) {
	u := c.Param("url")
	proxy.DefaultPool.ReportSuccess(u)
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

func (h *ProxyHandler) ReportFail(c *gin.Context) {
	u := c.Param("url")
	proxy.DefaultPool.ReportFail(u)
	c.JSON(http.StatusOK, gin.H{"ok": true})
}
