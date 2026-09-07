package v1

import (
	"strings"
)

// IsImageChatRequestFull 对等 conversation.py is_image_chat_request 全量
func IsImageChatRequestFull(messages []map[string]any) bool {
	for _, m := range messages {
		role, _ := m["role"].(string)
		if role != "user" {
			continue
		}
		if content, ok := m["content"].(string); ok {
			lower := strings.ToLower(content)
			if strings.Contains(lower, "画") || strings.Contains(lower, "image") || strings.Contains(lower, "photo") || strings.Contains(lower, "draw") {
				return true
			}
		}
		if arr, ok := m["content"].([]any); ok {
			for _, part := range arr {
				if pm, ok := part.(map[string]any); ok {
					if pm["type"] == "image_url" || pm["type"] == "image_asset_pointer" {
						return true
					}
				}
			}
		}
	}
	return false
}
