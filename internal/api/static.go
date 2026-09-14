package api

import (
	"embed"
	"io/fs"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
)

//go:embed all:web_dist
// all: 前缀嵌入包括 _ 开头在内的全部文件（Vite 公共 chunk 曾因目录模式跳过 _ 文件导致 SPA import 失败）
var embeddedFS embed.FS

// Static registers embedded FS with SPA fallback.
//
// 关键约束：SPA fallback 只对「页面路由」生效。未注册的 /api/* 与 /v1/*
// 必须返回 404 JSON，否则前端会把 index.html 当成功响应解析，
// 造成「保存成功但什么都没存」这类静默失败。
func (s *Server) RegisterStatic(r *gin.Engine, fsys fs.FS) {
	if fsys == nil {
		// 默认使用嵌入的 web_dist
		sub, _ := fs.Sub(embeddedFS, "web_dist")
		fsys = sub
	}
	r.NoRoute(func(c *gin.Context) {
		if isAPIPath(c.Request.URL.Path) {
			c.AbortWithStatusJSON(http.StatusNotFound, gin.H{"error": gin.H{
				"message": "接口不存在: " + c.Request.Method + " " + c.Request.URL.Path,
				"type":    "invalid_request_error",
				"code":    "route_not_found",
			}})
			return
		}
		// try serve file
		if _, err := fs.Stat(fsys, c.Request.URL.Path[1:]); err == nil {
			c.FileFromFS(c.Request.URL.Path, http.FS(fsys))
			return
		}
		// SPA fallback
		c.FileFromFS("/", http.FS(fsys))
	})
}

// isAPIPath 判断是否为后端接口路径（区别于 SPA 页面路由）。
func isAPIPath(path string) bool {
	return path == "/api" || strings.HasPrefix(path, "/api/") ||
		path == "/v1" || strings.HasPrefix(path, "/v1/")
}

// EmbeddedFS 供外部直接获取
func EmbeddedFS() fs.FS {
	sub, _ := fs.Sub(embeddedFS, "web_dist")
	return sub
}
