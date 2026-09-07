package protocol

// 对等 services/protocol/anthropic_v1_messages.py
type AnthropicMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type AnthropicRequest struct {
	Model    string             `json:"model"`
	Messages []AnthropicMessage `json:"messages"`
}

func ToOpenAI(req AnthropicRequest) []map[string]any {
	var out []map[string]any
	for _, m := range req.Messages {
		out = append(out, map[string]any{"role": m.Role, "content": m.Content})
	}
	return out
}
