package admin

import (
	"archive/zip"
	"bytes"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"chatgpt2api/internal/imageclean"

	"github.com/gin-gonic/gin"
)

// GalleryHandler 图片管理页（Gallery）。
// 前端契约（web_dist/assets/gallery-*.js）：
//
//	GET    /api/images?start_date&end_date&media_type&tag&search&limit&offset
//	       → {items,total,total_size,page,page_size,page_count,counts{all,image,video,music}}
//	       item: {path,rel,name,url,thumbnail_url,size,created_at,date,type,tags,storage,local,webdav}
//	GET    /api/images/file?path=...      → 原图/缩略图字节（前端 url 指向该路径）
//	POST   /api/images/delete {paths}     → {removed:N,success:true}
//	POST   /api/images/download {paths}   → zip blob
//	GET    /api/images/tags               → {tags:[...]}
//	POST   /api/images/tags {path,tags}
//	DELETE /api/images/tags/:tag
//	GET    /api/images/storage
//	POST   /api/images/storage/compress
//	POST   /api/images/storage/cleanup-to-target?target_free_mb&dry_run
type GalleryHandler struct {
	DataDir string
}

var imageExts = map[string]string{
	".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image",
	".gif": "image", ".bmp": "image",
	".mp4": "video", ".webm": "video", ".mov": "video", ".m4v": "video",
	".mp3": "music", ".wav": "music", ".ogg": "music", ".m4a": "music", ".flac": "music",
}

func (h *GalleryHandler) Register(r *gin.RouterGroup) {
	r.GET("/images", h.List)
	r.GET("/images/file", h.ServeFile)
	r.POST("/images/delete", h.Delete)
	r.POST("/images/download", h.Download)
	r.GET("/images/tags", h.ListTags)
	r.POST("/images/tags", h.UpdateTags)
	r.DELETE("/images/tags/:tag", h.DeleteTag)
	r.GET("/images/storage", h.StorageInfo)
	r.POST("/images/storage/compress", h.Compress)
	r.POST("/images/storage/cleanup-to-target", h.CleanupToTarget)
}

func (h *GalleryHandler) imagesDir() string {
	if h.DataDir != "" {
		return filepath.Join(h.DataDir, "images")
	}
	return "data/images"
}

// List 扫描 <DataDir>/images 下的媒体文件。
func (h *GalleryHandler) List(c *gin.Context) {
	limit := parseIntDefault(c.Query("limit"), 24)
	if limit < 1 {
		limit = 24
	}
	if limit > 200 {
		limit = 200
	}
	offset := parseIntDefault(c.Query("offset"), 0)
	if offset < 0 {
		offset = 0
	}
	mediaType := strings.TrimSpace(c.Query("media_type"))
	startDate := strings.TrimSpace(c.Query("start_date"))
	endDate := strings.TrimSpace(c.Query("end_date"))
	search := strings.ToLower(strings.TrimSpace(c.Query("search")))

	dir := h.imagesDir()
	type mediaItem struct {
		item    gin.H
		modUnix int64
		dateKey string
		kind    string
	}
	var found []mediaItem
	counts := gin.H{"all": 0, "image": 0, "video": 0, "music": 0}

	_ = filepath.Walk(dir, func(path string, info os.FileInfo, err error) error {
		if err != nil || info.IsDir() {
			return nil
		}
		ext := strings.ToLower(filepath.Ext(info.Name()))
		kind, ok := imageExts[ext]
		if !ok {
			return nil
		}
		rel, relErr := filepath.Rel(dir, path)
		if relErr != nil {
			return nil
		}
		rel = filepath.ToSlash(rel)
		dateKey := filepath.Base(filepath.Dir(rel))
		if len(dateKey) != 8 {
			dateKey = info.ModTime().Format("20060102")
		}
		if startDate != "" && dateKey < strings.ReplaceAll(startDate, "-", "") {
			return nil
		}
		if endDate != "" && dateKey > strings.ReplaceAll(endDate, "-", "") {
			return nil
		}
		if search != "" && !strings.Contains(strings.ToLower(info.Name()), search) {
			return nil
		}
		found = append(found, mediaItem{
			modUnix: info.ModTime().Unix(),
			dateKey: dateKey,
			kind:    kind,
			item: gin.H{
				"path":          rel,
				"rel":           rel,
				"name":          info.Name(),
				"url":           "/api/images/file?path=" + rel,
				"thumbnail_url": "/api/images/file?path=" + rel,
				"size":          info.Size(),
				"created_at":    info.ModTime().Unix(),
				"date":          dateKey,
				"type":          kind,
				"tags":          []string{},
				"storage":       "local",
				"local":         true,
				"webdav":        false,
			},
		})
		return nil
	})

	// 最新在前
	sort.Slice(found, func(i, j int) bool { return found[i].modUnix > found[j].modUnix })

	var totalSize int64
	for _, f := range found {
		totalSize += f.item["size"].(int64)
		counts["all"] = counts["all"].(int) + 1
		counts[f.kind] = counts[f.kind].(int) + 1
	}

	// media_type 过滤（all/image/video/music）
	selected := make([]gin.H, 0, len(found))
	for _, f := range found {
		if mediaType != "" && mediaType != "all" && f.kind != mediaType {
			continue
		}
		selected = append(selected, f.item)
	}

	total := len(selected)
	start := offset
	if start > total {
		start = total
	}
	end := start + limit
	if end > total {
		end = total
	}
	page := start/limit + 1
	pageCount := (total + limit - 1) / limit
	if pageCount < 1 {
		pageCount = 1
	}

	c.JSON(http.StatusOK, gin.H{
		"items":      selected[start:end],
		"total":      total,
		"total_size": totalSize,
		"page":       page,
		"page_size":  limit,
		"page_count": pageCount,
		"counts":     counts,
	})
}

// ServeFile 原图字节（前端 url / thumbnail_url 指向此路径）。
func (h *GalleryHandler) ServeFile(c *gin.Context) {
	dir := h.imagesDir()
	relPath := c.Query("path")
	if relPath == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"message": "path required"}})
		return
	}
	full := filepath.Join(dir, filepath.FromSlash(relPath))
	if !isSubPath(dir, full) {
		c.JSON(http.StatusForbidden, gin.H{"error": gin.H{"message": "forbidden"}})
		return
	}
	f, err := os.Open(full)
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": gin.H{"message": "not found"}})
		return
	}
	defer f.Close()
	c.Header("Cache-Control", "public, max-age=86400")
	c.Header("Content-Type", mimeForExt(full))
	_, _ = io.Copy(c.Writer, f)
}

// Delete POST /api/images/delete {paths}
func (h *GalleryHandler) Delete(c *gin.Context) {
	var body struct {
		Paths []string `json:"paths"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"success": false, "error": gin.H{"message": "invalid body"}})
		return
	}
	dir := h.imagesDir()
	removed := 0
	for _, p := range body.Paths {
		full := filepath.Join(dir, filepath.FromSlash(p))
		if !isSubPath(dir, full) {
			continue
		}
		if err := os.Remove(full); err == nil {
			removed++
		}
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "removed": removed})
}

// Download POST /api/images/download {paths} → zip
func (h *GalleryHandler) Download(c *gin.Context) {
	var body struct {
		Paths []string `json:"paths"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"message": "invalid body"}})
		return
	}
	dir := h.imagesDir()
	buf := &bytes.Buffer{}
	zw := zip.NewWriter(buf)
	added := 0
	used := map[string]int{}
	for _, p := range body.Paths {
		full := filepath.Join(dir, filepath.FromSlash(p))
		if !isSubPath(dir, full) {
			continue
		}
		data, err := os.ReadFile(full)
		if err != nil {
			continue
		}
		name := filepath.Base(p)
		if used[name] > 0 {
			ext := filepath.Ext(name)
			stem := strings.TrimSuffix(name, ext)
			used[name]++
			name = fmt.Sprintf("%s_%d%s", stem, used[name]+1, ext)
		} else {
			used[name] = 1
		}
		fw, err := zw.Create(name)
		if err != nil {
			continue
		}
		if _, err := fw.Write(data); err == nil {
			added++
		}
	}
	zw.Close()
	if added == 0 {
		c.JSON(http.StatusNotFound, gin.H{"error": gin.H{"message": "no images to download"}})
		return
	}
	c.Header("Content-Disposition", "attachment; filename=images.zip")
	c.Data(http.StatusOK, "application/zip", buf.Bytes())
}

// ListTags GET /api/images/tags
func (h *GalleryHandler) ListTags(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"tags": []string{}})
}

// UpdateTags POST /api/images/tags
func (h *GalleryHandler) UpdateTags(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"success": true})
}

// DeleteTag DELETE /api/images/tags/:tag
func (h *GalleryHandler) DeleteTag(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"success": true})
}

// StorageInfo GET /api/images/storage
func (h *GalleryHandler) StorageInfo(c *gin.Context) {
	dir := h.imagesDir()
	var totalSize int64
	var fileCount int
	_ = filepath.Walk(dir, func(path string, info os.FileInfo, err error) error {
		if err != nil || info.IsDir() {
			return nil
		}
		if _, ok := imageExts[strings.ToLower(filepath.Ext(info.Name()))]; !ok {
			return nil
		}
		totalSize += info.Size()
		fileCount++
		return nil
	})
	c.JSON(http.StatusOK, gin.H{
		"total_size": totalSize,
		"file_count": fileCount,
		"image_dir":  dir,
		"storage":    "local",
	})
}

// Compress POST /api/images/storage/compress
func (h *GalleryHandler) Compress(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"success": true, "message": "无需压缩"})
}

// CleanupToTarget POST /api/images/storage/cleanup-to-target?target_free_mb&dry_run
// 手动清理入口：按保留天数清过期目录（与后台 Cleaner 同一套规则）。
func (h *GalleryHandler) CleanupToTarget(c *gin.Context) {
	cl := &imageclean.Cleaner{DataDir: h.DataDir}
	if c.Query("dry_run") == "true" {
		c.JSON(http.StatusOK, gin.H{"success": true, "deleted": 0, "dry_run": true,
			"message": "预览模式：实际清理按保留天数由后台定时执行"})
		return
	}
	removed := cl.CleanupOnce()
	c.JSON(http.StatusOK, gin.H{"success": true, "deleted": removed, "dry_run": false})
}

// isSubPath 防越权：full 必须位于 base 目录内。
func isSubPath(base, full string) bool {
	absBase, err := filepath.Abs(base)
	if err != nil {
		return false
	}
	absFull, err := filepath.Abs(full)
	if err != nil {
		return false
	}
	rel, err := filepath.Rel(absBase, absFull)
	if err != nil {
		return false
	}
	return rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator))
}

func mimeForExt(path string) string {
	switch strings.ToLower(filepath.Ext(path)) {
	case ".png":
		return "image/png"
	case ".jpg", ".jpeg":
		return "image/jpeg"
	case ".webp":
		return "image/webp"
	case ".gif":
		return "image/gif"
	case ".bmp":
		return "image/bmp"
	case ".mp4":
		return "video/mp4"
	case ".webm":
		return "video/webm"
	case ".mp3":
		return "audio/mpeg"
	case ".wav":
		return "audio/wav"
	default:
		return "application/octet-stream"
	}
}
