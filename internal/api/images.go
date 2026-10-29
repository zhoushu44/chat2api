package api

import (
	"archive/zip"
	"encoding/json"
	"fmt"
	"io/fs"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
)

// ImagesHandler 本地图片库真实管理：列表、存储统计、下载、删除、标签。
// 图片目录固定为 <DataDir>/images，所有用户路径均限制在该目录内。
type ImagesHandler struct {
	DataDir string
}

type imageFile struct {
	Path      string   `json:"path"`
	Name      string   `json:"name"`
	URL       string   `json:"url"`
	Thumbnail string   `json:"thumbnail_url"`
	Size      int64    `json:"size"`
	CreatedAt string   `json:"created_at"`
	Type      string   `json:"type"`
	Tags      []string `json:"tags"`
	Storage   string   `json:"storage"`
	Local     bool     `json:"local"`
	Webdav    bool     `json:"webdav"`
}

func (h *ImagesHandler) Register(r *gin.RouterGroup) {
	r.GET("/images", h.List)
	r.GET("/images/storage", h.Storage)
	r.POST("/images/delete", h.Delete)
	r.POST("/images/download", h.Download)
	r.GET("/images/tags", h.Tags)
	r.POST("/images/tags", h.UpdateTags)
	r.DELETE("/images/tags/:tag", h.DeleteTag)
	r.GET("/images/download/*path", h.DownloadOne)
}

func (h *ImagesHandler) RegisterPublicImages(r *gin.RouterGroup) {
	r.GET("/images/*path", h.ServeImage)
}

func (h *ImagesHandler) root() string { return filepath.Join(h.DataDir, "images") }

func safeImageRel(raw string) (string, error) {
	clean := filepath.ToSlash(filepath.Clean(strings.TrimSpace(raw)))
	if clean == "" || clean == "." || clean == ".." || strings.HasPrefix(clean, "../") || filepath.IsAbs(clean) || strings.HasPrefix(clean, "/") {
		return "", fmt.Errorf("invalid image path")
	}
	return clean, nil
}

func (h *ImagesHandler) fullPath(rel string) (string, error) {
	clean, err := safeImageRel(rel)
	if err != nil {
		return "", err
	}
	root, err := filepath.Abs(h.root())
	if err != nil {
		return "", err
	}
	full, err := filepath.Abs(filepath.Join(root, filepath.FromSlash(clean)))
	if err != nil {
		return "", err
	}
	relCheck, err := filepath.Rel(root, full)
	if err != nil || relCheck == ".." || strings.HasPrefix(relCheck, "../") {
		return "", fmt.Errorf("invalid image path")
	}
	return full, nil
}

func imageMediaType(path string) string {
	switch strings.ToLower(filepath.Ext(path)) {
	case ".mp4", ".webm", ".mov", ".m4v":
		return "video"
	case ".mp3", ".wav", ".ogg", ".m4a", ".flac":
		return "music"
	default:
		return "image"
	}
}

func (h *ImagesHandler) tagsData() map[string][]string {
	out := map[string][]string{}
	b, err := os.ReadFile(filepath.Join(h.DataDir, "image_tags.json"))
	if err == nil {
		_ = json.Unmarshal(b, &out)
	}
	return out
}

func (h *ImagesHandler) saveTags(data map[string][]string) error {
	b, err := json.MarshalIndent(data, "", "  ")
	if err != nil {
		return err
	}
	tmp := filepath.Join(h.DataDir, "image_tags.json.tmp")
	if err := os.WriteFile(tmp, b, 0644); err != nil {
		return err
	}
	return os.Rename(tmp, filepath.Join(h.DataDir, "image_tags.json"))
}

func (h *ImagesHandler) scan() ([]imageFile, int64, error) {
	tags := h.tagsData()
	files := make([]imageFile, 0)
	var total int64
	err := filepath.WalkDir(h.root(), func(path string, entry fs.DirEntry, err error) error {
		if err != nil || entry.IsDir() {
			return nil
		}
		info, err := entry.Info()
		if err != nil {
			return nil
		}
		rel, err := filepath.Rel(h.root(), path)
		if err != nil {
			return nil
		}
		rel = filepath.ToSlash(rel)
		total += info.Size()
		files = append(files, imageFile{
			Path: rel, Name: entry.Name(), URL: "/v1/images/" + rel, Thumbnail: "/v1/images/" + rel,
			Size: info.Size(), CreatedAt: info.ModTime().UTC().Format(time.RFC3339),
			Type: imageMediaType(rel), Tags: tags[rel], Storage: "local", Local: true, Webdav: false,
		})
		return nil
	})
	if os.IsNotExist(err) {
		return files, 0, nil
	}
	return files, total, err
}

func (h *ImagesHandler) List(c *gin.Context) {
	files, totalSize, err := h.scan()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	media := c.Query("media_type")
	tag := c.Query("tag")
	search := strings.ToLower(strings.TrimSpace(c.Query("search")))
	startDate := c.Query("start_date")
	endDate := c.Query("end_date")
	filtered := make([]imageFile, 0, len(files))
	counts := gin.H{"all": 0, "image": 0, "video": 0, "music": 0}
	for _, f := range files {
		counts["all"] = counts["all"].(int) + 1
		counts[f.Type] = counts[f.Type].(int) + 1
		if media != "" && media != "all" && f.Type != media {
			continue
		}
		if tag != "" && tag != "all" && !containsString(f.Tags, tag) {
			continue
		}
		if search != "" && !strings.Contains(strings.ToLower(f.Path+" "+f.Name+" "+strings.Join(f.Tags, " ")), search) {
			continue
		}
		if startDate != "" && f.CreatedAt[:10] < startDate {
			continue
		}
		if endDate != "" && f.CreatedAt[:10] > endDate {
			continue
		}
		filtered = append(filtered, f)
	}
	sort.Slice(filtered, func(i, j int) bool { return filtered[i].CreatedAt > filtered[j].CreatedAt })
	limit := clampInt(c.DefaultQuery("limit", "24"), 0, 200)
	offset := clampInt(c.DefaultQuery("offset", "0"), 0, 10000000)
	total := len(filtered)
	start := minInt(offset, total)
	end := total
	if limit > 0 {
		end = minInt(start+limit, total)
	}
	pageSize := limit
	if pageSize <= 0 {
		pageSize = 24
	}
	page := start/pageSize + 1
	pageCount := (total + pageSize - 1) / pageSize
	if pageCount < 1 {
		pageCount = 1
	}
	c.JSON(http.StatusOK, gin.H{
		"items": filtered[start:end], "total": total, "total_size": totalSize,
		"counts": counts, "limit": limit, "offset": offset, "has_more": end < total,
		"page": page, "page_size": pageSize, "page_count": pageCount,
	})
}

func (h *ImagesHandler) Storage(c *gin.Context) {
	files, bytes, err := h.scan()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	total, free := diskUsage(h.root())
	c.JSON(http.StatusOK, gin.H{
		"disk_total_mb": total / 1024 / 1024,
		"disk_used_mb": (total - free) / 1024 / 1024,
		"disk_free_mb": free / 1024 / 1024,
		"image_count": len(files), "image_size_bytes": bytes,
		"image_size_mb": float64(bytes) / 1024 / 1024,
	})
}

func (h *ImagesHandler) Delete(c *gin.Context) {
	var body struct {
		Paths []string `json:"paths"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	removed := 0
	for _, rel := range body.Paths {
		path, err := h.fullPath(rel)
		if err != nil {
			continue
		}
		if err := os.Remove(path); err == nil {
			removed++
		}
	}
	c.JSON(http.StatusOK, gin.H{"removed": removed})
}

func (h *ImagesHandler) Download(c *gin.Context) {
	var body struct {
		Paths []string `json:"paths"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	if len(body.Paths) == 1 {
		h.downloadPath(c, body.Paths[0])
		return
	}
	c.Header("Content-Type", "application/zip")
	c.Header("Content-Disposition", `attachment; filename="images.zip"`)
	zw := zip.NewWriter(c.Writer)
	defer zw.Close()
	for _, rel := range body.Paths {
		path, err := h.fullPath(rel)
		if err != nil {
			continue
		}
		data, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		w, err := zw.Create(filepath.Base(path))
		if err == nil {
			_, _ = w.Write(data)
		}
	}
}

func (h *ImagesHandler) DownloadOne(c *gin.Context) {
	h.downloadPath(c, strings.TrimPrefix(c.Param("path"), "/"))
}

func (h *ImagesHandler) downloadPath(c *gin.Context, rel string) {
	path, err := h.fullPath(rel)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	c.FileAttachment(path, filepath.Base(path))
}

func (h *ImagesHandler) ServeImage(c *gin.Context) {
	path, err := h.fullPath(strings.TrimPrefix(c.Param("path"), "/"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	c.File(path)
}

func (h *ImagesHandler) Tags(c *gin.Context) {
	set := map[string]bool{}
	for _, tags := range h.tagsData() {
		for _, tag := range tags {
			set[tag] = true
		}
	}
	out := make([]string, 0, len(set))
	for tag := range set {
		out = append(out, tag)
	}
	sort.Strings(out)
	c.JSON(http.StatusOK, gin.H{"tags": out})
}

func (h *ImagesHandler) UpdateTags(c *gin.Context) {
	var body struct {
		Path string   `json:"path"`
		Tags []string `json:"tags"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	rel, err := safeImageRel(body.Path)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	data := h.tagsData()
	seen := map[string]bool{}
	clean := []string{}
	for _, tag := range body.Tags {
		tag = strings.TrimSpace(tag)
		if tag != "" && !seen[tag] {
			seen[tag] = true
			clean = append(clean, tag)
		}
	}
	data[rel] = clean
	if err := h.saveTags(data); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"ok": true, "tags": clean})
}

func (h *ImagesHandler) DeleteTag(c *gin.Context) {
	tag := c.Param("tag")
	data := h.tagsData()
	removed := 0
	for path, tags := range data {
		kept := make([]string, 0, len(tags))
		for _, current := range tags {
			if current != tag {
				kept = append(kept, current)
			}
		}
		if len(kept) != len(tags) {
			removed++
		}
		data[path] = kept
	}
	if err := h.saveTags(data); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"ok": true, "removed_from": removed})
}

func containsString(items []string, target string) bool {
	for _, item := range items {
		if item == target {
			return true
		}
	}
	return false
}
