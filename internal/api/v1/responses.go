package v1

import (
	"net/http"
	"strings"

	"chatgpt2api/internal/protocol"

	"github.com/gin-gonic/gin"
)

// HandleResponsesWith responses API 真实链路（P2.2）：
// - tools 含 image_generation → 图片事件序列（created → output_item.done → completed）
// - 其它 → 文本事件序列（created → added → delta* → done → item.done → completed）
// web_search 工具暂返回 501（protocol/search.go 为桩，见 TASKS.md P2）。
func HandleResponsesWith(c *gin.Context, orch *protocol.Orchestrator) {
	var req struct {
		Model        string `json:"model"`
		Input        any    `json:"input"`
		Instructions string `json:"instructions"`
		Stream       bool   `json:"stream"`
		Tools        []struct {
			Type string `json:"type"`
		} `json:"tools"`
	}
	_ = c.ShouldBindJSON(&req)
	hasImageTool := false
	hasSearchTool := false
	for _, t := range req.Tools {
		switch t.Type {
		case "image_generation":
			hasImageTool = true
		case "web_search", "web_search_preview":
			hasSearchTool = true
		}
	}
	if hasSearchTool && !hasImageTool {
		c.JSON(http.StatusNotImplemented, gin.H{"error": gin.H{
			"message": "web_search responses is not yet implemented in the Go port (protocol/search.go is a stub)",
			"type":    "api_error", "code": "not_implemented",
		}})
		return
	}
	if orch == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": gin.H{
			"message": "responses service unavailable: no account pool configured",
			"type":    "api_error", "code": "service_unavailable",
		}})
		return
	}
	model := strings.TrimSpace(req.Model)
	if hasImageTool {
		if model == "" || !strings.Contains(model, "image") {
			model = "gpt-image-2"
		}
		prompt := protocol.ExtractResponsePrompt(req.Input)
		if strings.TrimSpace(prompt) == "" {
			c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"message": "input text is required", "type": "invalid_request_error", "code": "invalid_input"}})
			return
		}
		events, err := protocol.StreamImageResponseEvents(c.Request.Context(), orch, prompt, model)
		if err != nil {
			c.JSON(http.StatusBadGateway, gin.H{"error": gin.H{"message": err.Error(), "type": "api_error", "code": "upstream_error"}})
			return
		}
		emitResponseEvents(c, req.Stream, events)
		return
	}
	// 文本路径
	if model == "" {
		model = "auto"
	}
	messages := protocol.MessagesFromInput(req.Input, req.Instructions)
	if len(messages) == 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"message": "input text is required", "type": "invalid_request_error", "code": "invalid_input"}})
		return
	}
	messages = protocol.NormalizeTextMessages(messages)
	effort := protocol.ThinkingEffortFromBody(map[string]any{"model": model})
	events, err := protocol.StreamTextResponseEvents(c.Request.Context(), orch, model, messages, effort)
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": gin.H{"message": err.Error(), "type": "api_error", "code": "upstream_error"}})
		return
	}
	emitResponseEvents(c, req.Stream, events)
}

// emitResponseEvents 输出事件：stream → SSE（event: type / data: payload）；
// 非 stream → 取 completed 的 response（对等 collect_response）。
func emitResponseEvents(c *gin.Context, stream bool, events []protocol.ResponseEvent) {
	if stream {
		c.Header("Content-Type", "text/event-stream")
		c.Header("Cache-Control", "no-cache")
		for _, ev := range events {
			c.SSEvent(ev.Type, ev.Payload)
			c.Writer.Flush()
		}
		c.String(http.StatusOK, "data: [DONE]\n\n")
		return
	}
	resp, err := protocol.CollectResponse(events)
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": gin.H{"message": err.Error(), "type": "api_error", "code": "upstream_error"}})
		return
	}
	c.JSON(http.StatusOK, resp)
}

// HandleResponses 兼容旧入口。
func HandleResponses(c *gin.Context) {
	HandleResponsesWith(c, nil)
}
