package api

import (
	"chatgpt2api/internal/config"

	"github.com/gin-gonic/gin"
)

// App 对等 api/app.py
func NewApp(cfg *config.Config) *gin.Engine {
	srv := &Server{Cfg: cfg}
	r := srv.NewRouter()
	// 面板路由可在此挂载 admin
	return r
}
