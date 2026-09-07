package api

import (
	"net/http"

	"chatgpt2api/internal/prompt"

	"github.com/gin-gonic/gin"
)

// 对等 api/prompts.py（CRUD + 分类）
func RegisterPrompts(r *gin.RouterGroup, svc *prompt.Service) {
	r.GET("/prompts", func(c *gin.Context) {
		category := c.Query("category")
		mode := c.Query("mode")
		_, quickOnly := c.GetQuery("quick")
		if category != "" || mode != "" || quickOnly {
			c.JSON(http.StatusOK, gin.H{"data": svc.Query(category, mode, quickOnly), "total": len(svc.Query(category, mode, quickOnly))})
			return
		}
		data := svc.List()
		c.JSON(http.StatusOK, gin.H{"data": data, "total": len(data)})
	})
	r.GET("/prompts/:id", func(c *gin.Context) {
		if p, ok := svc.Get(c.Param("id")); ok {
			c.JSON(http.StatusOK, p)
			return
		}
		c.JSON(http.StatusNotFound, gin.H{"error": "prompt not found"})
	})
	r.GET("/prompt-categories", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"data": svc.Categories()})
	})
	r.POST("/prompts", func(c *gin.Context) {
		var p prompt.Prompt
		if err := c.ShouldBindJSON(&p); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
			return
		}
		if err := svc.Add(&p); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
			return
		}
		c.JSON(http.StatusOK, p)
	})
	r.DELETE("/prompts/:id", func(c *gin.Context) {
		if err := svc.Delete(c.Param("id")); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}
		c.JSON(http.StatusOK, gin.H{"ok": true})
	})
}
