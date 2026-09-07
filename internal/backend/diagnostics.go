package backend

import (
	"encoding/json"
	"strings"
)

// 对等 utils/diagnostics.py + openai_backend_api.py 的诊断辅助

func diagnosticExcerpt(v any, limit int) string {
	var s string
	switch x := v.(type) {
	case string:
		s = x
	case error:
		s = x.Error()
	default:
		b, _ := json.Marshal(x)
		s = string(b)
	}
	if len(s) > limit {
		return s[:limit] + "...[truncated]"
	}
	return s
}

func terminalAssistantText(data map[string]any) string {
	mapping, _ := data["mapping"].(map[string]any)
	for _, nodeVal := range mapping {
		node, _ := nodeVal.(map[string]any)
		msg, _ := node["message"].(map[string]any)
		author, _ := msg["author"].(map[string]any)
		role, _ := author["role"].(string)
		if strings.ToLower(role) == "assistant" {
			if content, ok := msg["content"].(map[string]any); ok {
				if parts, ok := content["parts"].([]any); ok && len(parts) > 0 {
					if s, ok := parts[0].(string); ok {
						return s
					}
				}
			}
		}
	}
	return ""
}
