package api

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"time"

	"chatgpt2api/internal/account"
	v1 "chatgpt2api/internal/api/v1"
	"chatgpt2api/internal/backend/failure"
	"chatgpt2api/internal/protocol"
	"chatgpt2api/internal/task"
	"chatgpt2api/internal/utils"

	"github.com/gin-gonic/gin"
)

// RegisterImageTasks 挂载控制台「图像创作」页所需接口。
// 前端契约见 web-vue/src/api/imageTasks.ts：
//
//	GET  /api/image-tasks          → {items, missing_ids, quota_summary}
//	GET  /api/image-tasks/quota    → ImageQuotaSummary
//	POST /api/image-tasks/generations
//	POST /api/image-tasks/edits
//	POST /api/image-tasks/:id/resume-poll
func (s *Server) RegisterImageTasks(r *gin.RouterGroup) {
	r.GET("/image-tasks", s.handleImageTaskList)
	r.GET("/image-tasks/quota", s.handleImageTaskQuota)
	r.POST("/image-tasks/generations", s.handleImageTaskGeneration)
	r.POST("/image-tasks/edits", s.handleImageTaskEdit)
	r.POST("/image-tasks/:id/resume-poll", s.handleImageTaskResumePoll)
}

// handleImageTaskList 任务列表：ids 为空取全部；返回 missing_ids 供前端清理本地悬挂 id。
func (s *Server) handleImageTaskList(c *gin.Context) {
	if s.Tasks == nil {
		c.JSON(http.StatusOK, gin.H{"items": []any{}, "missing_ids": []string{}})
		return
	}
	var ids []string
	if raw := strings.TrimSpace(c.Query("ids")); raw != "" {
		for _, part := range strings.Split(raw, ",") {
			if id := strings.TrimSpace(part); id != "" {
				ids = append(ids, id)
			}
		}
	}
	items := s.Tasks.ListByIDs(ids)
	found := make(map[string]bool, len(items))
	for _, t := range items {
		found[t.ID] = true
	}
	missing := make([]string, 0)
	for _, id := range ids {
		if !found[id] {
			missing = append(missing, id)
		}
	}
	c.JSON(http.StatusOK, gin.H{
		"items":         items,
		"missing_ids":   missing,
		"quota_summary": s.imageQuotaSummary(),
	})
}

// handleImageTaskQuota 额度汇总。
func (s *Server) handleImageTaskQuota(c *gin.Context) {
	c.JSON(http.StatusOK, s.imageQuotaSummary())
}

// imageQuotaSummary 基于账号池统计（对等前端 ImageQuotaSummary 契约）。
func (s *Server) imageQuotaSummary() gin.H {
	summary := gin.H{
		"total_quota":           0,
		"unlimited_quota_count": 0,
		"unknown_quota_count":   0,
		"active_accounts":       0,
		"limited_accounts":      0,
		"abnormal_accounts":     0,
		"disabled_accounts":     0,
		"available":             false,
	}
	totalQuota := 0
	unlimited := 0
	unknown := 0
	active := 0
	limited := 0
	abnormal := 0
	disabled := 0
	for _, a := range s.imageAccounts() {
		switch {
		case a.Status == account.StatusDisabled:
			disabled++
		case a.Status == account.StatusLimited:
			limited++
		default:
			if a.ValidityStatus == "invalid" {
				abnormal++
			} else {
				active++
			}
		}
		if !a.Available() {
			continue
		}
		switch {
		case account.IsImageQuotaUnknown(a):
			unknown++
		case a.Quota < 0:
			unlimited++
		default:
			totalQuota += a.Quota
		}
	}
	summary["total_quota"] = totalQuota
	summary["unlimited_quota_count"] = unlimited
	summary["unknown_quota_count"] = unknown
	summary["active_accounts"] = active
	summary["limited_accounts"] = limited
	summary["abnormal_accounts"] = abnormal
	summary["disabled_accounts"] = disabled
	summary["available"] = totalQuota > 0 || unlimited > 0 || unknown > 0 || active > 0
	return summary
}

// imageAccounts 优先取号池（含运行态），回落持久化账号列表。
func (s *Server) imageAccounts() []*account.Account {
	if s.Pool != nil {
		if list := s.Pool.List(); len(list) > 0 {
			return list
		}
	}
	if s.Accounts != nil {
		return s.Accounts.List()
	}
	return nil
}

// imageTaskCreateInput 生成/编辑提交参数（表单与 JSON 共用）。
type imageTaskCreateInput struct {
	ClientTaskID string
	Prompt       string
	Model        string
	N            int
	Size         string
	Quality      string
	Mode         string
	Images       []string // data-URL 或 http(s) URL
}

// handleImageTaskGeneration 文生图：落库 queued 后异步编排，立即返回任务。
func (s *Server) handleImageTaskGeneration(c *gin.Context) {
	var req struct {
		ClientTaskID string `json:"client_task_id"`
		Prompt       string `json:"prompt"`
		Model        string `json:"model"`
		N            int    `json:"n"`
		Size         string `json:"size"`
		Quality      string `json:"quality"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"message": err.Error(), "type": "invalid_request_error", "code": "invalid_image_input"}})
		return
	}
	s.submitImageTask(c, imageTaskCreateInput{
		ClientTaskID: req.ClientTaskID, Prompt: req.Prompt, Model: req.Model,
		N: req.N, Size: req.Size, Quality: req.Quality, Mode: "generate",
	})
}

// handleImageTaskEdit 图生图：multipart（image/image[]/image_url/images）与 JSON 两种输入。
func (s *Server) handleImageTaskEdit(c *gin.Context) {
	in := imageTaskCreateInput{Mode: "edit"}
	if c.ContentType() == "multipart/form-data" {
		c.Request.ParseMultipartForm(64 << 20)
		in.ClientTaskID = c.PostForm("client_task_id")
		in.Prompt = c.PostForm("prompt")
		in.Model = c.PostForm("model")
		in.Size = c.PostForm("size")
		in.Quality = c.PostForm("quality")
		in.N = atoiDefault(c.PostForm("n"), 1)
		// 远程参考图 URL（单 url 或多 url JSON 数组）
		if v := strings.TrimSpace(c.PostForm("image_url")); v != "" {
			in.Images = append(in.Images, v)
		}
		if v := strings.TrimSpace(c.PostForm("images")); v != "" {
			in.Images = append(in.Images, parseURLListJSON(v)...)
		}
		if form, err := c.MultipartForm(); err == nil && form != nil {
			files := append(form.File["image"], form.File["image[]"]...)
			for _, fh := range files {
				f, err := fh.Open()
				if err != nil {
					continue
				}
				b, _ := io.ReadAll(io.LimitReader(f, 50<<20))
				f.Close()
				if len(b) == 0 {
					continue
				}
				mime := fh.Header.Get("Content-Type")
				if mime == "" {
					mime = http.DetectContentType(b)
				}
				in.Images = append(in.Images, "data:"+mime+";base64,"+base64.StdEncoding.EncodeToString(b))
			}
		}
	} else {
		var req struct {
			ClientTaskID string   `json:"client_task_id"`
			Prompt       string   `json:"prompt"`
			Model        string   `json:"model"`
			N            int      `json:"n"`
			Size         string   `json:"size"`
			Quality      string   `json:"quality"`
			Image        string   `json:"image"`
			ImageURL     string   `json:"image_url"`
			Images       []string `json:"images"`
		}
		if err := c.ShouldBindJSON(&req); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"message": err.Error(), "type": "invalid_request_error", "code": "invalid_image_input"}})
			return
		}
		in.ClientTaskID, in.Prompt, in.Model = req.ClientTaskID, req.Prompt, req.Model
		in.N, in.Size, in.Quality = req.N, req.Size, req.Quality
		if req.Image != "" {
			in.Images = append(in.Images, req.Image)
		}
		if req.ImageURL != "" {
			in.Images = append(in.Images, req.ImageURL)
		}
		in.Images = append(in.Images, req.Images...)
	}
	s.submitImageTask(c, in)
}

func (s *Server) submitImageTask(c *gin.Context, in imageTaskCreateInput) {
	if strings.TrimSpace(in.Prompt) == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"message": "prompt required", "type": "invalid_request_error", "code": "invalid_image_input"}})
		return
	}
	if s.Tasks == nil || s.Orch == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": gin.H{
			"message": "image generation service unavailable: no account pool configured",
			"type":    "api_error", "code": "service_unavailable",
		}})
		return
	}
	if in.Model == "" {
		in.Model = "gpt-image-2"
	}
	if in.Quality == "" {
		in.Quality = "auto"
	}
	if in.N <= 0 {
		in.N = 1
	}
	if in.N > 4 {
		in.N = 4
	}
	if in.Mode == "" {
		in.Mode = "generate"
	}
	id := strings.TrimSpace(in.ClientTaskID)
	if id == "" {
		id = utils.NewUUID()
	}
	if _, ok := s.Tasks.Get(id); ok {
		id = utils.NewUUID() // 防重放覆盖
	}

	t := s.Tasks.Save(&task.Task{
		ID:       id,
		Status:   task.Queued,
		Mode:     in.Mode,
		Model:    in.Model,
		N:        in.N,
		Size:     in.Size,
		Quality:  in.Quality,
		Stage:    "queued",
		CanResume: true,
	})
	go s.runImageTask(t.ID, in)

	c.JSON(http.StatusOK, t)
}

// runImageTask 异步执行真实生图链路并回写任务状态。
func (s *Server) runImageTask(id string, in imageTaskCreateInput) {
	start := time.Now()
	s.Tasks.UpdateFunc(id, func(t *task.Task) {
		t.Status = task.Running
		t.Stage = "running"
		t.Progress = "account_acquire"
	})

	// 远程参考图先落地为 data-URL（与 /v1/images/edits 同口径）。
	images := make([]string, 0, len(in.Images))
	for _, im := range in.Images {
		if v1.IsHTTPURL(im) {
			dataURI, err := v1.DownloadImageURL(context.Background(), im)
			if err != nil {
				s.failImageTask(id, start, "invalid_image_input", "invalid_image_input", err.Error())
				return
			}
			images = append(images, dataURI)
			continue
		}
		images = append(images, im)
	}

	s.Tasks.UpdateFunc(id, func(t *task.Task) { t.Progress = "upstream_sse" })
	res, err := s.Orch.Generate(context.Background(), protocol.GenerateRequest{
		Prompt: protocol.BuildImagePrompt(in.Prompt, in.Size, in.Quality),
		Model:  in.Model,
		Images: images,
		N:      in.N,
	})
	if err != nil {
		f := failure.Classify(err, 0, err.Error())
		code := f.Code
		if code == "" {
			code = "upstream_error"
		}
		msg := err.Error()
		if code == "content_policy_violation" {
			msg = "content policy violation"
		}
		s.failImageTask(id, start, code, f.ErrorType, msg)
		return
	}

	assets := make([]task.Asset, 0, in.N)
	for i := 0; i < in.N; i++ {
		item := task.Asset{RevisedPrompt: in.Prompt}
		switch {
		case i < len(res.B64) && len(res.B64[i]) > 0:
			item.B64JSON = string(res.B64[i])
		case i < len(res.URLs):
			item.URL = res.URLs[i]
		default:
			continue
		}
		assets = append(assets, item)
	}
	if len(assets) == 0 {
		s.failImageTask(id, start, "upstream_error", "no_images", "upstream returned no images")
		return
	}
	durationMs := time.Since(start).Milliseconds()
	s.Tasks.UpdateFunc(id, func(t *task.Task) {
		t.Status = task.Success
		t.Stage = "completed"
		t.Progress = "completed"
		t.Data = assets
		t.DurationMS = durationMs
		t.ElapsedSec = float64(durationMs) / 1000
		t.Error = ""
		t.ErrorCode = ""
		t.Reason = ""
		t.CanResume = false
	})
}

// failImageTask 统一失败回写。
func (s *Server) failImageTask(id string, start time.Time, code, upstreamType, msg string) {
	durationMs := time.Since(start).Milliseconds()
	s.Tasks.UpdateFunc(id, func(t *task.Task) {
		t.Status = task.Error
		t.Stage = "error"
		t.Progress = ""
		t.Error = msg
		t.ErrorCode = code
		t.Reason = msg
		t.UpstreamErrorTyp = upstreamType
		t.DurationMS = durationMs
		t.ElapsedSec = float64(durationMs) / 1000
		t.CanResume = true
	})
}

// handleImageTaskResumePoll 恢复轮询：把任务重置为 queued，前端下一轮 list 继续拉取。
func (s *Server) handleImageTaskResumePoll(c *gin.Context) {
	if s.Tasks == nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "not found"})
		return
	}
	t, ok := s.Tasks.MarkResumable(c.Param("id"))
	if !ok {
		c.JSON(http.StatusNotFound, gin.H{"error": "not found"})
		return
	}
	c.JSON(http.StatusOK, t)
}

func atoiDefault(v string, def int) int {
	v = strings.TrimSpace(v)
	if v == "" {
		return def
	}
	n := 0
	for _, r := range v {
		if r < '0' || r > '9' {
			return def
		}
		n = n*10 + int(r-'0')
	}
	if n == 0 {
		return def
	}
	return n
}

// parseURLListJSON 解析 "[a,b]" 或裸 URL 文本为 URL 列表。
func parseURLListJSON(v string) []string {
	v = strings.TrimSpace(v)
	if v == "" {
		return nil
	}
	if strings.HasPrefix(v, "[") {
		var out []string
		if err := json.Unmarshal([]byte(v), &out); err == nil {
			return out
		}
	}
	parts := strings.Split(v, "\n")
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		if p = strings.TrimSpace(strings.Trim(p, ",")); p != "" {
			out = append(out, p)
		}
	}
	return out
}
