package api

import (
	"embed"
	"io/fs"
	"net/http"

	"github.com/gin-gonic/gin"
)

//go:embed web_dist
// 目录模式会跳过 _ 开头文件，Vite 公共 chunk 必须显式嵌入，否则 SPA 按 index.html 回退导致 import 失败
//go:embed web_dist/assets/_plugin-vue_export-helper-DlAUqK2U.js
var embeddedFS embed.FS

// Static registers embedded FS with SPA fallback.
func (s *Server) RegisterStatic(r *gin.Engine, fsys fs.FS) {
	if fsys == nil {
		// 默认使用嵌入的 web_dist
		sub, _ := fs.Sub(embeddedFS, "web_dist")
		fsys = sub
	}
	r.NoRoute(func(c *gin.Context) {
		// try serve file
		if _, err := fs.Stat(fsys, c.Request.URL.Path[1:]); err == nil {
			c.FileFromFS(c.Request.URL.Path, http.FS(fsys))
			return
		}
		// SPA fallback
		c.FileFromFS("/", http.FS(fsys))
	})
}

// EmbeddedFS 供外部直接获取
func EmbeddedFS() fs.FS {
	sub, _ := fs.Sub(embeddedFS, "web_dist")
	return sub
}
