package protocol

import (
	"strings"
	"time"

	"chatgpt2api/internal/utils"

	"github.com/google/uuid"
)

// chat 帧构造与 usage（P2.1）：对等 openai_v1_chat_complete.completion_chunk /
// completion_response / text_chat_parts（thinking_effort 归一见 reasoning.go 扩展）。

// CompletionChunk SSE chunk 帧（对等 completion_chunk）。
func CompletionChunk(model string, delta map[string]any, finishReason, completionID string, created int64) map[string]any {
	if completionID == "" {
		completionID = "chatcmpl-" + uuid.NewString()
	}
	if created == 0 {
		created = time.Now().Unix()
	}
	return map[string]any{
		"id":      completionID,
		"object":  "chat.completion.chunk",
		"created": created,
		"model":   model,
		"choices": []any{map[string]any{"index": 0, "delta": delta, "finish_reason": finishReason}},
	}
}

// ChatUsage usage 块（对等 completion_response 的 usage；token 用 utils.CountTokens 近似）。
func ChatUsage(messages []map[string]any, content, model string) map[string]any {
	promptText := countMessagesTextTokens(messages)
	completion := 0
	if messages != nil {
		completion = utils.CountTokens(content)
	}
	total := promptText + completion
	return map[string]any{
		"prompt_tokens":     promptText,
		"completion_tokens": completion,
		"total_tokens":      total,
		"prompt_tokens_details": map[string]any{
			"text_tokens":   promptText,
			"image_tokens":  0,
			"cached_tokens": 0,
		},
		"completion_tokens_details": map[string]any{
			"text_tokens":      completion,
			"image_tokens":     0,
			"reasoning_tokens": 0,
		},
	}
}

func countMessagesTextTokens(messages []map[string]any) int {
	total := 0
	for _, m := range messages {
		total += utils.CountTokens(MessageText(m["content"]))
	}
	return total
}

// CompletionResponse 非流式响应体（对等 completion_response）。
func CompletionResponse(model, content string, messages []map[string]any) map[string]any {
	msg := map[string]any{"role": "assistant", "content": content}
	return map[string]any{
		"id":      "chatcmpl-" + uuid.NewString(),
		"object":  "chat.completion",
		"created": time.Now().Unix(),
		"model":   model,
		"choices": []any{map[string]any{
			"index": 0, "message": msg, "finish_reason": "stop",
		}},
		"usage": ChatUsage(messages, content, model),
	}
}

// CollectChunks 聚合 chunk 序列为完整文本（对等 collect_chat_content）。
func CollectChunks(chunks []map[string]any) string {
	var b strings.Builder
	for _, ch := range chunks {
		choices, _ := ch["choices"].([]any)
		if len(choices) == 0 {
			continue
		}
		first, _ := choices[0].(map[string]any)
		if first == nil {
			continue
		}
		delta, _ := first["delta"].(map[string]any)
		if delta == nil {
			continue
		}
		if s, ok := delta["content"].(string); ok {
			b.WriteString(s)
		}
	}
	return b.String()
}

// ChatMessagesFromBody 请求解析（对等 chat_messages_from_body）：
// messages 数组优先，否则 prompt 字符串兜底。
func ChatMessagesFromBody(body map[string]any) ([]map[string]any, error) {
	if arr, ok := body["messages"].([]any); ok && len(arr) > 0 {
		out := make([]map[string]any, 0, len(arr))
		for _, m := range arr {
			if mp, ok := m.(map[string]any); ok {
				out = append(out, mp)
			}
		}
		if len(out) > 0 {
			return out, nil
		}
	}
	if prompt, _ := body["prompt"].(string); strings.TrimSpace(prompt) != "" {
		return []map[string]any{{"role": "user", "content": strings.TrimSpace(prompt)}}, nil
	}
	return nil, errMissingMessages
}

type protocolError string

func (e protocolError) Error() string { return string(e) }

const errMissingMessages = protocolError("messages or prompt is required")

// MessageText 消息 content 转纯文本（string 直接取；list 取 text part）。
func MessageText(content any) string {
	if s, ok := content.(string); ok {
		return s
	}
	if arr, ok := content.([]any); ok {
		var b strings.Builder
		for _, p := range arr {
			if pm, ok := p.(map[string]any); ok && pm["type"] == "text" {
				if t, ok := pm["text"].(string); ok {
					b.WriteString(t)
				}
			}
		}
		return b.String()
	}
	return ""
}

// NormalizeTextMessages 消息规范化（对等 normalize_messages 的核心：
// 过滤空消息、string 化 content；相邻重复消息去重——对等 Python 默认 drop_adjacent_duplicates=True）。
func NormalizeTextMessages(messages []map[string]any) []map[string]any {
	out := make([]map[string]any, 0, len(messages))
	var prevSig string
	for _, m := range messages {
		role, _ := m["role"].(string)
		if role == "" {
			role = "user"
		}
		text := MessageText(m["content"])
		sig := role + "\x00" + text
		if sig == prevSig {
			continue // 相邻重复去重
		}
		prevSig = sig
		out = append(out, map[string]any{"role": role, "content": text})
	}
	return out
}

// ThinkingEffortFromBody 推理强度归一（对等 reasoning.thinking_effort_from_body）。
func ThinkingEffortFromBody(body map[string]any) string {
	if v, ok := body["thinking_effort"]; ok {
		return NormalizeThinkingEffort(v)
	}
	if v, ok := body["reasoning_effort"]; ok {
		return NormalizeThinkingEffort(v)
	}
	if r, ok := body["reasoning"].(map[string]any); ok {
		return NormalizeThinkingEffort(r["effort"])
	}
	return ""
}

// NormalizeThinkingEffort 对等 normalize_thinking_effort。
func NormalizeThinkingEffort(value any) string {
	s, _ := value.(string)
	switch strings.ToLower(strings.TrimSpace(s)) {
	case "", "none":
		return ""
	case "low", "medium", "high":
		return strings.ToLower(strings.TrimSpace(s))
	case "xhigh", "extended":
		return "extended"
	default:
		return ""
	}
}
