package utils

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"strings"
)

// 对等 utils/helper.py 部分
func NewUUID() string {
	b := make([]byte, 16)
	_, _ = rand.Read(b)
	b[6] = (b[6] & 0x0f) | 0x40
	b[8] = (b[8] & 0x3f) | 0x80
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:])
}

func IsImageChatRequest(messages []map[string]any) bool {
	for _, m := range messages {
		if content, ok := m["content"].(string); ok && strings.Contains(strings.ToLower(content), "image") {
			return true
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

func DiagnosticExcerpt(v any, limit int) string {
	s := fmt.Sprintf("%v", v)
	if len(s) > limit {
		return s[:limit] + "...[truncated]"
	}
	return s
}

func HexID(n int) string {
	b := make([]byte, n)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}
