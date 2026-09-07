package admin

import (
	"net/http"

	"chatgpt2api/internal/config"
	"chatgpt2api/internal/model"

	"github.com/gin-gonic/gin"
)

type SystemHandler struct {
	Cfg *config.Config
	// Catalog 模型目录（P1.4，可为 nil 则该路由返回 fallback 快照）
	Catalog *model.Catalog
}

func (h *SystemHandler) Register(r *gin.RouterGroup) {
	r.GET("/config", h.GetConfig)
	r.PUT("/config", h.UpdateConfig)
	r.GET("/health", h.Health)
	// P1.4 /api/model-catalog（对等 Python system.py 该端点；嵌入的 web_dist 前端依赖）
	r.GET("/model-catalog", h.ModelCatalog)
}

func (h *SystemHandler) GetConfig(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"data_dir": h.Cfg.DataDir, "storage_backend": h.Cfg.StorageType})
}
func (h *SystemHandler) UpdateConfig(c *gin.Context) {
	var body map[string]any
	_ = c.ShouldBindJSON(&body)
	c.JSON(http.StatusOK, gin.H{"ok": true})
}
func (h *SystemHandler) Health(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"status": "ok"})
}

// ModelCatalog 模型目录快照（P1.4）。Catalog 为 nil 时返回 fallback 快照。
func (h *SystemHandler) ModelCatalog(c *gin.Context) {
	if h.Catalog == nil {
		c.JSON(http.StatusOK, model.New().Snapshot())
		return
	}
	c.JSON(http.StatusOK, h.Catalog.Snapshot())
}
