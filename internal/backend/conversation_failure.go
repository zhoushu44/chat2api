package backend

import (
	"strings"
)

// 会话失败速败（对等 Python classify_conversation_failure + classify_message_facts 最小子集）。
//
// 空轮询时若当前轮已出现终态失败证据，立即返回明确错误，不再闷轮 60s。
// 调用方保证：fileIDs/sedimentIDs 为空时才调（有指针说明图已在途）。
// 仅判定当前轮（最后一条 user 之后的消息），避免历史轮次误伤。
// structured-code 全表未移植：命中则按下述四条返回，未命中返回 "" 交给继续轮询。
func ClassifyConversationFailure(raw map[string]any) (code, detail string) {
	mapping, _ := raw["mapping"].(map[string]any)
	if len(mapping) == 0 {
		return "", ""
	}
	type cmsg struct {
		t  float64
		id string
		m  map[string]any
	}
	var msgs []cmsg
	for id, nv := range mapping {
		node, _ := nv.(map[string]any)
		if node == nil {
			continue
		}
		msg, _ := node["message"].(map[string]any)
		if msg == nil {
			continue
		}
		var t float64
		switch v := msg["create_time"].(type) {
		case float64:
			t = v
		case int64:
			t = float64(v)
		}
		msgs = append(msgs, cmsg{t: t, id: id, m: msg})
	}
	// 按 (create_time, id) 排序后取最后一条 user 之后（对等 _current_conversation_turn）。
	for i := 1; i < len(msgs); i++ {
		j := i
		for j > 0 && (msgs[j].t < msgs[j-1].t || (msgs[j].t == msgs[j-1].t && msgs[j].id < msgs[j-1].id)) {
			msgs[j], msgs[j-1] = msgs[j-1], msgs[j]
			j--
		}
	}
	turn := msgs
	for i, cm := range msgs {
		if convRole(cm.m) == "user" {
			turn = msgs[i+1:]
		}
	}
	for _, cm := range turn {
		if c, d := classifyTurnMessage(cm.m); c != "" {
			return c, d
		}
	}
	return "", ""
}

var terminalStatuses = map[string]bool{
	"complete": true, "completed": true, "done": true, "finished": true,
	"finished_successfully": true, "finished_partial_completion": true,
	"success": true, "succeeded": true,
}

var failedStatuses = map[string]bool{
	"error": true, "fail": true, "failed": true,
	"limited": true, "rate_limited": true, "限流": true,
}

func convStr(v any) string {
	s, _ := v.(string)
	return strings.ToLower(strings.TrimSpace(s))
}

func convRole(msg map[string]any) string {
	author, _ := msg["author"].(map[string]any)
	if author == nil {
		return ""
	}
	return convStr(author["role"])
}

func convText(msg map[string]any) string {
	content, _ := msg["content"].(map[string]any)
	if content == nil {
		return ""
	}
	var b strings.Builder
	if parts, ok := content["parts"].([]any); ok {
		for _, p := range parts {
			if s, ok := p.(string); ok {
				b.WriteString(s)
			}
		}
	}
	if s, ok := content["text"].(string); ok {
		b.WriteString(s)
	}
	return strings.TrimSpace(b.String())
}

// classifyTurnMessage 单条当前轮消息判定（对等 classify_message_facts 的终态分支）。
func classifyTurnMessage(msg map[string]any) (string, string) {
	metadata, _ := msg["metadata"].(map[string]any)
	content, _ := msg["content"].(map[string]any)
	role := convRole(msg)
	ctype := ""
	if content != nil {
		ctype = convStr(content["content_type"])
	}
	status := convStr(msg["status"])
	if metadata != nil {
		if status == "" {
			status = convStr(metadata["status"])
		}
	}
	if isTrue(msg["blocked"]) || (metadata != nil && isTrue(metadata["blocked"])) {		return "content_policy_violation", trunc(convText(msg), 500)
	}
	endTurn, _ := msg["end_turn"].(bool)
	text := convText(msg)
	if role == "assistant" && (ctype == "text" || ctype == "code") &&
		(endTurn || terminalStatuses[status]) && text != "" && !looksLikeJSON(text) {
		return "upstream_text_reply", trunc(text, 500)
	}
	if role == "tool" && ctype == "system_error" {
		return "image_tool_error", trunc(text, 500)
	}
	isErr := isTrue(msg["is_error"]) || (metadata != nil && (isTrue(metadata["is_error"]) || metadata["error"] != nil)) || msg["error"] != nil
	if isErr || failedStatuses[status] {
		if status == "limited" || status == "rate_limited" || status == "限流" {
			return "upstream_rate_limited", trunc(text+" "+status, 500)
		}
		return "upstream_error", trunc(text+" "+status, 500)
	}
	return "", ""
}

func isTrue(v any) bool {
	b, _ := v.(bool)
	return b
}

// looksLikeJSON 控制帧排除：工具调用 envelope 之类的 JSON 文本不是自然语言回复，
// 不得作为终态文本证据（线上曾见 {"skipped_mainline":true} 误杀正常生图）。
func looksLikeJSON(s string) bool {
	t := strings.TrimSpace(s)
	if len(t) < 2 {
		return false
	}
	return (t[0] == '{' && t[len(t)-1] == '}') || (t[0] == '[' && t[len(t)-1] == ']')
}

func trunc(s string, n int) string {
	s = strings.TrimSpace(s)
	if len(s) <= n {
		return s
	}
	return s[:n]
}
