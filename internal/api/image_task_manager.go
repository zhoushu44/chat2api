package api

import (
	"context"
	"encoding/base64"
	"io"
	"net/http"
	"strings"
	"sync"
	"time"

	"chatgpt2api/internal/account"
	"chatgpt2api/internal/backend/failure"
	"chatgpt2api/internal/protocol"
	"chatgpt2api/internal/task"

	"github.com/gin-gonic/gin"
)

// ImageTasksHandler 图像创作任务：真实创建、查询、额度摘要与续轮询。
type ImageTasksHandler struct {
	Tasks    *task.Service
	Orch     *protocol.Orchestrator
	Accounts *account.Service
	mu       sync.Mutex
	modes    map[string]string
	prompts  map[string]string
}

func (h *ImageTasksHandler) Register(r *gin.RouterGroup) {
	r.GET("/image-tasks", h.List)
	r.GET("/image-tasks/quota", h.Quota)
	r.POST("/image-tasks/generations", h.CreateGeneration)
	r.POST("/image-tasks/edits", h.CreateEdit)
	r.POST("/image-tasks/:id/resume-poll", h.ResumePoll)
}

func (h *ImageTasksHandler) init() {
	h.mu.Lock()
	if h.modes == nil {
		h.modes = map[string]string{}
		h.prompts = map[string]string{}
	}
	h.mu.Unlock()
}

func (h *ImageTasksHandler) List(c *gin.Context) {
	if h.Tasks == nil {
		c.JSON(http.StatusOK, gin.H{"items": []any{}, "missing_ids": []string{}})
		return
	}
	ids := map[string]bool{}
	for _, id := range strings.Split(c.Query("ids"), ",") {
		if id = strings.TrimSpace(id); id != "" {
			ids[id] = true
		}
	}
	items := make([]any, 0)
	missing := []string{}
	for _, t := range h.Tasks.List() {
		if len(ids) > 0 && !ids[t.ID] {
			continue
		}
		items = append(items, taskView(t))
		delete(ids, t.ID)
	}
	for id := range ids {
		missing = append(missing, id)
	}
	c.JSON(http.StatusOK, gin.H{"items": items, "missing_ids": missing})
}

func taskView(t *task.Task) gin.H {
	out := gin.H{
		"id": t.ID, "status": t.Status, "created_at": t.CreatedAt, "updated_at": t.UpdatedAt,
		"can_resume_poll": t.CanResume, "error": t.Error,
	}
	if t.Result != nil {
		out["data"] = t.Result
	}
	return out
}

func (h *ImageTasksHandler) Quota(c *gin.Context) {
	out := gin.H{"total_quota": 0, "unlimited_quota_count": 0, "unknown_quota_count": 0,
		"active_accounts": 0, "limited_accounts": 0, "abnormal_accounts": 0,
		"disabled_accounts": 0, "available": false}
	if h.Accounts != nil {
		for _, a := range h.Accounts.List() {
			if a.QuotaUnknown {
				out["unknown_quota_count"] = out["unknown_quota_count"].(int) + 1
			} else if a.Quota < 0 {
				out["unlimited_quota_count"] = out["unlimited_quota_count"].(int) + 1
			} else {
				out["total_quota"] = out["total_quota"].(int) + a.Quota
			}
			switch a.Status {
			case account.StatusNormal:
				out["active_accounts"] = out["active_accounts"].(int) + 1
			case account.StatusLimited:
				out["limited_accounts"] = out["limited_accounts"].(int) + 1
			case account.StatusDisabled:
				out["disabled_accounts"] = out["disabled_accounts"].(int) + 1
			default:
				out["abnormal_accounts"] = out["abnormal_accounts"].(int) + 1
			}
		}
	}
	out["available"] = out["active_accounts"].(int) > 0
	c.JSON(http.StatusOK, out)
}

type generationTaskRequest struct {
	ClientTaskID string `json:"client_task_id"`
	Prompt       string `json:"prompt"`
	Model        string `json:"model"`
	N            int    `json:"n"`
	Size         string `json:"size"`
	Quality      string `json:"quality"`
}

func (h *ImageTasksHandler) CreateGeneration(c *gin.Context) {
	var req generationTaskRequest
	if err := c.ShouldBindJSON(&req); err != nil || strings.TrimSpace(req.Prompt) == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "prompt required"})
		return
	}
	if req.N <= 0 {
		req.N = 1
	}
	if req.N > 4 {
		req.N = 4
	}
	if req.Model == "" {
		req.Model = "gpt-image-2"
	}
	if req.Quality == "" {
		req.Quality = "auto"
	}
	if req.ClientTaskID == "" {
		req.ClientTaskID = "gen-" + time.Now().Format("20060102-150405.000000000")
	}
	h.init()
	h.mu.Lock()
	h.modes[req.ClientTaskID] = "generate"
	h.prompts[req.ClientTaskID] = req.Prompt
	h.mu.Unlock()
	t := h.Tasks.Create(req.ClientTaskID)
	go h.runGeneration(t.ID, protocol.GenerateRequest{
		Prompt: protocol.BuildImagePrompt(req.Prompt, req.Size, req.Quality), Model: req.Model, N: req.N,
	})
	c.JSON(http.StatusAccepted, taskView(t))
}

func (h *ImageTasksHandler) CreateEdit(c *gin.Context) {
	prompt := strings.TrimSpace(c.PostForm("prompt"))
	if prompt == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "prompt required"})
		return
	}
	model := c.DefaultPostForm("model", "gpt-image-2")
	size := c.PostForm("size")
	quality := c.DefaultPostForm("quality", "auto")
	id := c.DefaultPostForm("client_task_id", "edit-"+time.Now().Format("20060102-150405.000000000"))
	n := clampInt(c.DefaultPostForm("n", "1"), 1, 4)
	images := []string{}
	form, err := c.MultipartForm()
	if err == nil && form != nil {
		for _, fh := range append(form.File["image"], form.File["image[]"]...) {
			f, err := fh.Open()
			if err != nil {
				continue
			}
			data, err := readAllLimit(f, 50<<20)
			_ = f.Close()
			if err == nil && len(data) > 0 {
				images = append(images, "data:image/png;base64,"+encodeB64String(data))
			}
		}
	}
	h.init()
	h.mu.Lock()
	h.modes[id] = "edit"
	h.prompts[id] = prompt
	h.mu.Unlock()
	t := h.Tasks.Create(id)
	go h.runGeneration(t.ID, protocol.GenerateRequest{
		Prompt: protocol.BuildImagePrompt(prompt, size, quality), Model: model, Images: images, N: n,
	})
	c.JSON(http.StatusAccepted, taskView(t))
}

func (h *ImageTasksHandler) runGeneration(id string, req protocol.GenerateRequest) {
	if h.Orch == nil {
		h.Tasks.Update(id, task.Error, nil, "生图服务未初始化")
		return
	}
	res, err := h.Orch.Generate(context.Background(), req)
	if err != nil {
		f := failure.Classify(err, 0, err.Error())
		h.Tasks.Update(id, task.Error, gin.H{"error_code": f.Code}, err.Error())
		return
	}
	data := make([]gin.H, 0, len(res.B64)+len(res.URLs))
	for _, b := range res.B64 {
		data = append(data, gin.H{"b64_json": string(b)})
	}
	for _, u := range res.URLs {
		data = append(data, gin.H{"url": u})
	}
	h.Tasks.Update(id, task.Success, data, "")
}

func encodeB64String(data []byte) string { return base64.StdEncoding.EncodeToString(data) }

func readAllLimit(r io.Reader, limit int64) ([]byte, error) {
	return io.ReadAll(io.LimitReader(r, limit))
}

func (h *ImageTasksHandler) ResumePoll(c *gin.Context) {
	id := c.Param("id")
	t, ok := h.Tasks.Get(id)
	if !ok {
		c.JSON(http.StatusNotFound, gin.H{"error": "task not found"})
		return
	}
	if !t.CanResume {
		c.JSON(http.StatusConflict, gin.H{"error": "task cannot resume"})
		return
	}
	h.init()
	h.mu.Lock()
	req := protocol.GenerateRequest{Prompt: h.prompts[id], Model: "gpt-image-2", N: 1}
	h.mu.Unlock()
	t.Status = task.Running
	t.UpdatedAt = time.Now()
	go h.runGeneration(id, req)
	c.JSON(http.StatusAccepted, taskView(t))
}
