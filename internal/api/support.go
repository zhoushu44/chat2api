package api

import "github.com/gin-gonic/gin"

// 对等 api/support.py
func Health(c *gin.Context) {
	c.JSON(200, gin.H{"status": "ok"})
}

func Version(c *gin.Context) {
	c.JSON(200, gin.H{"version": "v2.7.0-go"})
}
