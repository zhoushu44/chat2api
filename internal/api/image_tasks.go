package api

import (
	"net/http"

	"chatgpt2api/internal/task"

	"github.com/gin-gonic/gin"
)

// 对等 api/image_tasks.py
func RegisterImageTasks(r *gin.RouterGroup, svc *task.Service) {
	r.GET("/tasks", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"data": svc.List()})
	})
	r.GET("/tasks/:id", func(c *gin.Context) {
		if t, ok := svc.Get(c.Param("id")); ok {
			c.JSON(http.StatusOK, t)
			return
		}
		c.JSON(http.StatusNotFound, gin.H{"error": "not found"})
	})
}
