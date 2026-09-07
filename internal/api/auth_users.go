package api

import (
	"net/http"

	"chatgpt2api/internal/auth"

	"github.com/gin-gonic/gin"
)

// RegisterAuthUsers 用户密钥管理（P2.6）：对等 accounts.py /api/auth/users 四端点。
// 挂载方已做 admin 鉴权（require_admin）。
func RegisterAuthUsers(r *gin.RouterGroup, svc *auth.Service) {
	r.GET("/auth/users", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"items": svc.ListKeys(auth.RoleUser)})
	})
	r.POST("/auth/users", func(c *gin.Context) {
		var body struct {
			Name string `json:"name"`
		}
		_ = c.ShouldBindJSON(&body)
		item, raw, err := svc.CreateKey(auth.RoleUser, body.Name)
		if err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"message": err.Error()}})
			return
		}
		c.JSON(http.StatusOK, gin.H{"item": item, "key": raw, "items": svc.ListKeys(auth.RoleUser)})
	})
	r.POST("/auth/users/:id", func(c *gin.Context) {
		var body struct {
			Name    *string `json:"name"`
			Enabled *bool   `json:"enabled"`
			Key     *string `json:"key"`
		}
		_ = c.ShouldBindJSON(&body)
		if body.Name == nil && body.Enabled == nil && body.Key == nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"message": "还没有检测到改动，请修改后再保存"}})
			return
		}
		item, err := svc.UpdateKey(c.Param("id"), auth.KeyUpdate{
			Name: body.Name, Enabled: body.Enabled, Key: body.Key,
		}, auth.RoleUser)
		if err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"message": err.Error()}})
			return
		}
		if item == nil {
			c.JSON(http.StatusNotFound, gin.H{"error": gin.H{"message": "这条用户密钥不存在，可能已经被删除"}})
			return
		}
		c.JSON(http.StatusOK, gin.H{"item": item, "items": svc.ListKeys(auth.RoleUser)})
	})
	r.DELETE("/auth/users/:id", func(c *gin.Context) {
		if !svc.DeleteKey(c.Param("id"), auth.RoleUser) {
			c.JSON(http.StatusNotFound, gin.H{"error": gin.H{"message": "这条用户密钥不存在，可能已经被删除"}})
			return
		}
		c.JSON(http.StatusOK, gin.H{"items": svc.ListKeys(auth.RoleUser)})
	})
}
