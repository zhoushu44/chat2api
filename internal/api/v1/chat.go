package v1

import (
	"fmt"
	"net/http"
	"strings"
	"time"

	"chatgpt2api/internal/protocol"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
)

func newChatID() string { return uuid.NewString() }
func nowUnix() int64    { return time.Now().Unix() }

func isImageChatRequest(req map[string]any) bool {
	msgs, _ := req["messages"].([]any)
	for _, m := range msgs {
		if mp, ok := m.(map[string]any); ok {
			if content, ok := mp["content"].(string); ok && containsImageKeyword(content) {
				return true
			}
			if arr, ok := mp["content"].([]any); ok {
				for _, part := range arr {
					if pm, ok := part.(map[string]any); ok {
						if pm["type"] == "image_url" {
							return true
						}
					}
				}
			}
		}
	}
	return false
}

func containsImageKeyword(content string) bool {
	lower := strings.ToLower(content)
	for _, kw := range []string{"图片", "image", "photo", "draw", "paint", "画"} {
		if strings.Contains(lower, kw) {
			return true
		}
	}
	return false
}

// HandleChatCompletionsWith chat completions 真实链路（P0.2）：
// 图片场景（文本含图关键词或带 image_url 内容）→ orchestrator 生图并把 URL 以 markdown 返回；
// 纯文本场景返回 501（文本对话链路属 TASKS.md P2.1，不假装成功）。
func HandleChatCompletionsWith(c *gin.Context, orch *protocol.Orchestrator) {
	var req map[string]any
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"message": err.Error(), "type": "invalid_request_error"}})
		return
	}
	stream, _ := req["stream"].(bool)
	model, _ := req["model"].(string)
	if model == "" {
		model = "gpt-4o"
	}
	if !isImageChatRequest(req) {
		handleTextChat(c, orch, req, model, stream)
		return
	}
	if orch == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": gin.H{
			"message": "image generation service unavailable: no account pool configured",
			"type":    "api_error", "code": "service_unavailable",
		}})
		return
	}
	// 提取生图 prompt：取最后一条 user 消息文本
	prompt := extractLastUserText(req)
	if prompt == "" {
		prompt = "generate an image"
	}
	imageModel := imageModelFor(model)
	if !stream {
		res, err := orch.Generate(c.Request.Context(), protocol.GenerateRequest{Prompt: prompt, Model: imageModel, N: 1})
		if err != nil {
			c.JSON(http.StatusBadGateway, gin.H{"error": gin.H{"message": err.Error(), "type": "api_error", "code": "upstream_error"}})
			return
		}
		imageURL, ok := firstImageURL(res)
		if !ok {
			c.JSON(http.StatusBadGateway, gin.H{"error": gin.H{"message": "upstream returned no images", "type": "api_error", "code": "upstream_error"}})
			return
		}
		content := fmt.Sprintf("![image](%s)", imageURL)
		id := "chatcmpl-" + newChatID()
		c.JSON(http.StatusOK, gin.H{
			"id": id, "object": "chat.completion", "model": model,
			"choices": []gin.H{{"index": 0, "message": gin.H{"role": "assistant", "content": content}, "finish_reason": "stop"}},
		})
		return
	}
	// 流式：progress 文本 chunks + 最终图片 markdown（对等 stream_image_chat_completion）
	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	completionID := "chatcmpl-" + newChatID()
	created := nowUnix()
	sentRole := false
	sendDelta := func(content string, withRole bool) {
		delta := map[string]any{"content": content}
		if withRole {
			delta = map[string]any{"role": "assistant", "content": content}
			sentRole = true
		}
		c.SSEvent("", protocol.CompletionChunk(model, delta, "", completionID, created))
		c.Writer.Flush()
	}
	res, err := orch.GenerateStream(c.Request.Context(), protocol.GenerateRequest{Prompt: prompt, Model: imageModel, N: 1}, func(out protocol.ImageOutput) {
		switch out.Kind {
		case protocol.ImageOutputProgress:
			if out.Text != "" {
				sendDelta(out.Text, !sentRole)
			}
		case protocol.ImageOutputMessage:
			if out.Text != "" {
				sendDelta(out.Text, !sentRole)
			}
		}
	})
	if err != nil {
		c.SSEvent("", map[string]any{"error": map[string]any{"message": err.Error(), "type": "api_error", "code": "upstream_error"}})
		return
	}
	imageURL, ok := firstImageURL(res)
	if !ok {
		c.SSEvent("", map[string]any{"error": map[string]any{"message": "upstream returned no images", "type": "api_error", "code": "upstream_error"}})
		return
	}
	sendDelta(fmt.Sprintf("![image](%s)", imageURL), !sentRole)
	c.SSEvent("", protocol.CompletionChunk(model, map[string]any{}, "stop", completionID, created))
	c.String(http.StatusOK, "data: [DONE]\n\n")
}

// firstImageURL 取首图 URL（B64 转 data URI）。
func firstImageURL(res *protocol.GenerateResult) (string, bool) {
	if res == nil {
		return "", false
	}
	if len(res.URLs) > 0 {
		return res.URLs[0], true
	}
	if len(res.B64) > 0 {
		return "data:image/png;base64," + string(res.B64[0]), true
	}
	return "", false
}

func extractLastUserText(req map[string]any) string {
	msgs, _ := req["messages"].([]any)
	for i := len(msgs) - 1; i >= 0; i-- {
		if mp, ok := msgs[i].(map[string]any); ok {
			if role, _ := mp["role"].(string); role == "user" {
				if content, ok := mp["content"].(string); ok {
					return content
				}
			}
		}
	}
	return ""
}

// imageModelFor 将对话模型映射为生图模型（对齐 Python is_image_chat_request 后的模型选择）。
func imageModelFor(model string) string {
	if strings.Contains(model, "image") {
		return model
	}
	return "gpt-image-2"
}

// handleTextChat 文本对话真实链路（P2.1）：orchestrator.StreamText。
// 帧序列对等 stream_text_chat_completion：首帧带 role，后续纯 content，末帧 stop。
func handleTextChat(c *gin.Context, orch *protocol.Orchestrator, req map[string]any, model string, stream bool) {
	if orch == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": gin.H{
			"message": "text chat service unavailable: no account pool configured",
			"type":    "api_error", "code": "service_unavailable",
		}})
		return
	}
	messages, err := protocol.ChatMessagesFromBody(req)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"message": err.Error(), "type": "invalid_request_error", "code": "invalid_request"}})
		return
	}
	messages = protocol.NormalizeTextMessages(messages)
	effort := protocol.ThinkingEffortFromBody(req)
	if stream {
		completionID := "chatcmpl-" + newChatID()
		created := nowUnix()
		c.Header("Content-Type", "text/event-stream")
		c.Header("Cache-Control", "no-cache")
		sentRole := false
		_, _, streamErr := orch.StreamText(c.Request.Context(), protocol.TextRequest{
			Messages: messages, Model: model, ThinkingEffort: effort,
		}, func(delta string) {
			if delta == "" {
				return
			}
			var frame map[string]any
			if !sentRole {
				sentRole = true
				frame = protocol.CompletionChunk(model, map[string]any{"role": "assistant", "content": delta}, "", completionID, created)
			} else {
				frame = protocol.CompletionChunk(model, map[string]any{"content": delta}, "", completionID, created)
			}
			c.SSEvent("", frame)
			c.Writer.Flush()
		})
		if streamErr != nil {
			c.SSEvent("", map[string]any{"error": map[string]any{"message": streamErr.Error(), "type": "api_error", "code": "upstream_error"}})
			return
		}
		if !sentRole {
			c.SSEvent("", protocol.CompletionChunk(model, map[string]any{"role": "assistant", "content": ""}, "", completionID, created))
		}
		c.SSEvent("", protocol.CompletionChunk(model, map[string]any{}, "stop", completionID, created))
		c.String(http.StatusOK, "data: [DONE]\n\n")
		return
	}
	text, _, err := orch.StreamText(c.Request.Context(), protocol.TextRequest{
		Messages: messages, Model: model, ThinkingEffort: effort,
	}, nil)
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": gin.H{"message": err.Error(), "type": "api_error", "code": "upstream_error"}})
		return
	}
	c.JSON(http.StatusOK, protocol.CompletionResponse(model, text, messages))
}

// HandleChatCompletions 兼容旧入口。
func HandleChatCompletions(c *gin.Context) {
	HandleChatCompletionsWith(c, nil)
}
