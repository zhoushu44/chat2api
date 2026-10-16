package v1

import (
	"log"
	"net/http"

	"chatgpt2api/internal/backend/failure"
	"chatgpt2api/internal/protocol"

	"github.com/gin-gonic/gin"
)

// HandleGenerationsWith 生图真实链路（P0.2）：/v1/images/generations → orchestrator。
// orch 为 nil（服务未组装）时返回 503 而非假数据。
func HandleGenerationsWith(c *gin.Context, orch *protocol.Orchestrator) {
	var req struct {
		Prompt         string `json:"prompt" binding:"required"`
		Model          string `json:"model"`
		N              int    `json:"n"`
		ResponseFormat string `json:"response_format"`
		Size           string `json:"size"`
		Quality        string `json:"quality"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"message": err.Error(), "type": "invalid_request_error", "code": "invalid_image_input"}})
		return
	}
	if orch == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": gin.H{
			"message": "image generation service unavailable: no account pool configured",
			"type":    "api_error", "code": "service_unavailable",
		}})
		return
	}
	if req.N == 0 {
		req.N = 1
	}
	if req.N > 4 {
		req.N = 4
	}
	if req.ResponseFormat == "" {
		req.ResponseFormat = "b64_json"
	}
	if req.Model == "" {
		req.Model = "gpt-image-2"
	}
	quality := req.Quality
	if quality == "" {
		quality = "auto"
	}
	res, err := orch.Generate(c.Request.Context(), protocol.GenerateRequest{
		Prompt: protocol.BuildImagePrompt(req.Prompt, req.Size, quality), Model: req.Model, N: req.N,
	})
	if err != nil {
		// 失败分类统一映射：本地输入错误 400（不换号不冷却），上游错误 502（换号冷却）。
		f := failure.Classify(err, 0, err.Error())
		code, httpStatus := f.Code, f.StatusCode
		if httpStatus == 0 {
			code, httpStatus = "upstream_error", http.StatusBadGateway
		}
		msg := err.Error()
		if code == "content_policy_violation" {
			msg = "content policy violation"
		}
		c.JSON(httpStatus, gin.H{"error": gin.H{"message": msg, "type": "invalid_request_error", "code": code}})
		return
	}
	data := make([]gin.H, 0, req.N)
	for i := 0; i < req.N; i++ {
		item := gin.H{"revised_prompt": req.Prompt}
		if req.ResponseFormat == "url" {
			if i < len(res.URLs) {
				item["url"] = res.URLs[i]
			}
		} else {
			if i < len(res.B64) {
				item["b64_json"] = string(res.B64[i])
			}
		}
		data = append(data, item)
	}
	if len(data) == 0 {
		c.JSON(http.StatusBadGateway, gin.H{"error": gin.H{"message": "upstream returned no images", "type": "api_error", "code": "upstream_error"}})
		return
	}
	t := res.Timing
	log.Printf("[images] model=%s n=%d total=%dms pick=%d boot=%d reqs=%d prep=%d sse=%dms initwait=%d pollwait=%d polls=%d resolve=%d dl=%d enc=%d",
		req.Model, req.N, t.TotalMs, t.AccountPickMs, t.BootstrapMs, t.RequirementsMs, t.PrepareMs,
		t.SSEStreamMs, t.InitialWaitMs, t.PollWaitMs, t.PollCount, t.ResolveMs, t.DownloadMs, t.EncodeMs)
	c.JSON(http.StatusOK, gin.H{"created": 0, "data": data})
}

// HandleGenerations 兼容旧入口（无依赖注入时明确 503，不再返回假图）。
func HandleGenerations(c *gin.Context) {
	HandleGenerationsWith(c, nil)
}
