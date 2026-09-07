package api

import (
	"net/http"

	"github.com/gin-gonic/gin"
)

// 对等 api/errors.py
func AbortWithError(c *gin.Context, status int, code, message string) {
	c.AbortWithStatusJSON(status, gin.H{
		"error": gin.H{
			"message": message,
			"type":    "api_error",
			"code":    code,
		},
	})
}

func NotFound(c *gin.Context) {
	AbortWithError(c, http.StatusNotFound, "not_found", "not found")
}
