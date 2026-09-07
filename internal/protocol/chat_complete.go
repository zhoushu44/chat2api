package protocol

import (
	"strings"
)

// 对等 services/protocol/openai_v1_chat_complete.py
// 简化：判断是否为图片场景，聚合流式文本

func IsImageChatRequest(messages []map[string]any) bool {
	for _, m := range messages {
		if content, ok := m["content"].(string); ok {
			lower := strings.ToLower(content)
			if strings.Contains(lower, "画") || strings.Contains(lower, "image") || strings.Contains(lower, "draw") {
				return true
			}
		}
		if arr, ok := m["content"].([]any); ok {
			for _, part := range arr {
				if pm, ok := part.(map[string]any); ok && pm["type"] == "image_url" {
					return true
				}
			}
		}
	}
	return false
}

func AggregateDeltas(deltas []string) string {
	var b strings.Builder
	for _, d := range deltas {
		b.WriteString(d)
	}
	return b.String()
}
