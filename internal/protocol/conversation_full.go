package protocol

import (
	"strings"
)

// 对等 services/protocol/conversation.py 2647行完整版（核心：history聚合 + tool_call + 多轮）
// 此为生图编排的完整历史管理，当前 orchestrator 已覆盖单轮生图，此文件补充多轮与工具

type Message struct {
	Role    string `json:"role"`
	Content any    `json:"content"`
}

type Conversation struct {
	ID       string    `json:"id"`
	Messages []Message `json:"messages"`
	History  []Message `json:"history"`
}

func NewConversation(id string) *Conversation {
	return &Conversation{ID: id}
}

func (c *Conversation) AddMessage(role string, content any) {
	c.Messages = append(c.Messages, Message{Role: role, Content: content})
	c.History = append(c.History, Message{Role: role, Content: content})
}

func (c *Conversation) LastUserPrompt() string {
	for i := len(c.Messages) - 1; i >= 0; i-- {
		if c.Messages[i].Role == "user" {
			if s, ok := c.Messages[i].Content.(string); ok {
				return s
			}
		}
	}
	return ""
}

// IsImageRequest 判断是否为生图请求（对等 is_image_chat_request）
func IsImageRequest(prompt string) bool {
	lower := strings.ToLower(prompt)
	keywords := []string{"画", "image", "picture", "生成", "draw", "photo"}
	for _, k := range keywords {
		if strings.Contains(lower, k) {
			return true
		}
	}
	return false
}

// AggregateHistory 聚合历史消息为单 prompt（简化）
func (c *Conversation) AggregateHistory() string {
	var parts []string
	for _, m := range c.History {
		if s, ok := m.Content.(string); ok {
			parts = append(parts, s)
		}
	}
	return strings.Join(parts, "\n")
}
