package protocol

import (
	"encoding/json"
	"regexp"
	"strings"
)

// 文本 SSE 解析（P2.1/P2.4）：对等 conversation.py 的
// assistant_raw_text / assistant_message_text / apply_text_patch /
// sanitize_output_text / strip_history / iter_conversation_payloads delta 逻辑。

// AssistantMessageText 从 web message 提取文本（对等 assistant_message_text）。
func AssistantMessageText(message map[string]any) string {
	if message == nil {
		return ""
	}
	content, _ := message["content"].(map[string]any)
	if content == nil {
		return ""
	}
	if parts, ok := content["parts"].([]any); ok && len(parts) > 0 {
		var b strings.Builder
		for _, p := range parts {
			if s, ok := p.(string); ok {
				b.WriteString(s)
			}
		}
		if b.Len() > 0 {
			return b.String()
		}
	}
	// content_type "code" 时文本在 text 字段
	s, _ := content["text"].(string)
	return s
}

// StripHistory 去除历史回显前缀（对等 strip_history）。
func StripHistory(text, history string) string {
	for history != "" && strings.HasPrefix(text, history) {
		text = text[len(history):]
	}
	return text
}

// ApplyTextPatch 文本补丁 op（对等 apply_text_patch / apply_patch_op）。
func ApplyTextPatch(event map[string]any, current, history string) string {
	if event == nil {
		return current
	}
	if p, ok := event["p"].(string); ok && (p == "/message/content/parts/0" || p == "/message/content/text") {
		return applyPatchOp(event, current, history)
	}
	ops := event["v"]
	if s, ok := ops.(string); ok && current != "" {
		if _, hasP := event["p"]; !hasP {
			if _, hasO := event["o"]; !hasO {
				return current + s
			}
		}
	}
	if o, _ := event["o"].(string); o == "patch" {
		if list, ok := ops.([]any); ok {
			text := current
			for _, item := range list {
				if m, ok := item.(map[string]any); ok {
					text = ApplyTextPatch(m, text, history)
				}
			}
			return text
		}
	}
	if list, ok := ops.([]any); ok {
		text := current
		for _, item := range list {
			if m, ok := item.(map[string]any); ok {
				text = ApplyTextPatch(m, text, history)
			}
		}
		return text
	}
	return current
}

func applyPatchOp(op map[string]any, current, history string) string {
	o, _ := op["o"].(string)
	v, _ := op["v"].(string)
	switch o {
	case "append":
		return current + v
	case "replace":
		return StripHistory(v, history)
	default:
		return current
	}
}

// EventAssistantText 单事件 assistant 文本（对等 event_assistant_text）。
func EventAssistantText(event map[string]any, history string) string {
	candidates := []any{event}
	if v, ok := event["v"].(map[string]any); ok {
		candidates = append(candidates, v)
	}
	for _, c := range candidates {
		m, ok := c.(map[string]any)
		if !ok {
			continue
		}
		msg, ok := m["message"].(map[string]any)
		if !ok {
			continue
		}
		author, _ := msg["author"].(map[string]any)
		if role, _ := author["role"].(string); role != "assistant" {
			continue
		}
		return StripHistory(AssistantMessageText(msg), history)
	}
	return ""
}

// AssistantRawText 单事件累计文本（对等 assistant_raw_text）。
func AssistantRawText(event map[string]any, current, history string) string {
	candidates := []any{event}
	if v, ok := event["v"].(map[string]any); ok {
		candidates = append(candidates, v)
	}
	for _, c := range candidates {
		m, ok := c.(map[string]any)
		if !ok {
			continue
		}
		msg, ok := m["message"].(map[string]any)
		if !ok {
			continue
		}
		author, _ := msg["author"].(map[string]any)
		role, _ := author["role"].(string)
		if !strings.EqualFold(strings.TrimSpace(role), "assistant") {
			continue
		}
		if text := AssistantMessageText(msg); text != "" {
			return StripHistory(text, history)
		}
	}
	return ApplyTextPatch(event, current, history)
}

var (
	annotationRe  = regexp.MustCompile("\uE200([^\uE201]*)\uE201")
	trailingAnnRe = regexp.MustCompile("\uE200[^\uE201]*$")
	spacePunctRe  = regexp.MustCompile(`\s+([.,;:!?])`)
	turnTagRe     = regexp.MustCompile(`(?i)^turn\d+[a-z]*\d*$|^turn\d+\w*$`)
)

// SanitizeOutputText 去除 web 富标注（对等 sanitize_output_text）。
func SanitizeOutputText(text string) string {
	text = annotationRe.ReplaceAllStringFunc(text, func(match string) string {
		inner := match[len("\uE200") : len(match)-len("\uE201")]
		parts := strings.Split(inner, "\uE202")
		for i := range parts {
			parts[i] = strings.TrimSpace(parts[i])
		}
		kind := ""
		data := []string{}
		if len(parts) > 0 {
			kind = strings.ToLower(parts[0])
			data = parts[1:]
		}
		switch kind {
		case "url":
			label, url := "", ""
			if len(data) > 0 {
				label = data[0]
			}
			if len(data) > 1 {
				url = data[1]
			}
			if label != "" && (strings.HasPrefix(url, "http://") || strings.HasPrefix(url, "https://")) {
				return label + " (" + url + ")"
			}
			if label != "" {
				return label
			}
			return url
		case "cite":
			return readableAnnotationPart(data)
		default:
			return readableAnnotationPart(data)
		}
	})
	text = trailingAnnRe.ReplaceAllString(text, "")
	text = spacePunctRe.ReplaceAllString(text, "$1")
	return text
}

func readableAnnotationPart(parts []string) string {
	for _, p := range parts {
		v := strings.TrimSpace(p)
		if v == "" || isInternalAnnotationPart(v) {
			continue
		}
		return v
	}
	return ""
}

func isInternalAnnotationPart(part string) bool {
	v := strings.TrimSpace(part)
	if v == "" {
		return true
	}
	lower := strings.ToLower(v)
	if turnTagRe.MatchString(lower) {
		return true
	}
	return strings.HasPrefix(lower, "turn") || strings.HasPrefix(lower, "source")
}

// TextStreamParser 文本 SSE 解析状态机（对等 iter_conversation_payloads 的 delta 部分）。
type TextStreamParser struct {
	RawText  string
	Text     string
	history  string
	histMsgs []string // 历史 assistant 消息（对等 history_messages：命中即跳过回显）
	histIdx  int
	Finished bool
}

// NewTextStreamParser 创建解析器（historyText 为 assistant 历史回显前缀）。
func NewTextStreamParser(historyText string) *TextStreamParser {
	return &TextStreamParser{history: historyText}
}

// NewTextStreamParserWithHistory 带历史消息列表的解析器（对话续写去重）。
func NewTextStreamParserWithHistory(historyText string, historyMessages []string) *TextStreamParser {
	return &TextStreamParser{history: historyText, histMsgs: historyMessages}
}

// Feed 输入原始 SSE payload，返回本次增量 delta（空串表示无增量）。
func (p *TextStreamParser) Feed(payload string) string {
	if payload == "" {
		return ""
	}
	if payload == "[DONE]" {
		p.Finished = true
		return ""
	}
	var event map[string]any
	if err := json.Unmarshal([]byte(payload), &event); err != nil {
		return ""
	}
	// 历史消息去重（对等 iter_conversation_payloads 的 history_index 逻辑）：
	// 上游续写时先回放历史 assistant 文本，命中即清空累积并跳过。
	if p.histIdx < len(p.histMsgs) && EventAssistantText(event, p.history) == p.histMsgs[p.histIdx] {
		p.histIdx++
		p.RawText = ""
		p.Text = ""
		return ""
	}
	nextRaw := AssistantRawText(event, p.RawText, p.history)
	p.RawText = nextRaw
	nextText := SanitizeOutputText(nextRaw)
	var delta string
	if strings.HasPrefix(nextText, p.Text) {
		delta = nextText[len(p.Text):]
	} else {
		delta = nextText
	}
	p.Text = nextText
	return delta
}
