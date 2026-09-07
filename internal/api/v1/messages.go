package v1

import (
	"net/http"

	"chatgpt2api/internal/protocol"
	"chatgpt2api/internal/utils"

	"github.com/gin-gonic/gin"
)

// HandleMessagesWith anthropic messages 真实链路（P2.3）。
// 非流式 → protocol.MessageResponse（含 tool_use/end_turn 的 stop_reason 映射）；
// 流式 → message_start → block_start → delta* → stop → message_delta → message_stop。
func HandleMessagesWith(c *gin.Context, orch *protocol.Orchestrator) {
	var body map[string]any
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"message": err.Error(), "type": "invalid_request_error"}})
		return
	}
	if orch == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": gin.H{
			"message": "messages service unavailable: no account pool configured",
			"type":    "api_error",
		}})
		return
	}
	req := protocol.MessageRequestFromBody(body)
	if len(req.Messages) == 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"message": "messages is required", "type": "invalid_request_error"}})
		return
	}
	stream, _ := body["stream"].(bool)
	if stream {
		events, err := protocol.StreamAnthropicText(c.Request.Context(), orch, req)
		if err != nil {
			c.JSON(http.StatusBadGateway, gin.H{"error": gin.H{"message": err.Error(), "type": "api_error"}})
			return
		}
		c.Header("Content-Type", "text/event-stream")
		c.Header("Cache-Control", "no-cache")
		for _, ev := range events {
			c.SSEvent(ev.Type, ev.Payload)
			c.Writer.Flush()
		}
		return
	}
	text, _, err := orch.StreamText(c.Request.Context(), protocol.TextRequest{
		Messages: req.Messages, Model: req.Model,
	}, nil)
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": gin.H{"message": err.Error(), "type": "api_error"}})
		return
	}
	inputTokens := 0
	for _, m := range req.Messages {
		inputTokens += utils.CountTokens(protocol.MessageText(m["content"]))
	}
	c.JSON(http.StatusOK, protocol.MessageResponse(req.Model, text, inputTokens, utils.CountTokens(text), req.Tools))
}

// HandleMessages 兼容旧入口。
func HandleMessages(c *gin.Context) {
	HandleMessagesWith(c, nil)
}
