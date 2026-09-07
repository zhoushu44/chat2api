package protocol

import (
	"context"
	"encoding/json"
	"html"
	"regexp"
	"strings"
	"time"

	"chatgpt2api/internal/utils"

	"github.com/google/uuid"
)

// anthropic messages 协议（P2.3）：对等 anthropic_v1_messages.py。
// system 合并、多模态 content blocks、stop_reason 映射（tool_use/end_turn）、
// XML tool_calls 解析、SSE 事件序列（message_start → block_start → delta* → stop → message_delta → message_stop）。

// XMLToolRule 工具缺失时的系统提示（对等 TOOL_UNAVAILABLE_SYSTEM_MESSAGE 简化：工具走 XML 透传）。
const XMLToolRule = "Tool output adapter: when calling tools, output ONLY this XML and no prose/markdown:\n<tool_calls><tool_call><tool_name>TOOL_NAME</tool_name><parameters><PARAM><![CDATA[value]]></PARAM></parameters></tool_call></tool_calls>"

// MessageRequest anthropic 请求（对等 MessageRequest）。
type MessageRequest struct {
	Messages []map[string]any
	Model    string
	Tools    []any
	System   any
}

// BuildToolPrompt 工具提示块（对等 build_tool_prompt）。
func BuildToolPrompt(tools []any) string {
	var blocks []string
	for _, t := range tools {
		tm, ok := t.(map[string]any)
		if !ok {
			continue
		}
		name, desc, schema := toolMeta(tm)
		if name == "" {
			continue
		}
		schemaJSON, _ := json.Marshal(schema)
		blocks = append(blocks, "Tool: "+name+"\nDescription: "+desc+"\nParameters: "+string(schemaJSON))
	}
	if len(blocks) == 0 {
		return ""
	}
	return "Available tools:\n" + strings.Join(blocks, "\n") + "\n\nTool use rules:\n- To call tools, output ONLY XML and no prose/markdown:\n<tool_calls><tool_call><tool_name>TOOL_NAME</tool_name><parameters><PARAM><![CDATA[value]]></PARAM></parameters></tool_call></tool_calls>\n- Put parameters under <parameters> using the exact schema names."
}

func toolMeta(tool map[string]any) (name, desc string, schema any) {
	fn, _ := tool["function"].(map[string]any)
	if fn == nil {
		fn = map[string]any{}
	}
	name, _ = tool["name"].(string)
	if name == "" {
		name, _ = fn["name"].(string)
	}
	name = strings.TrimSpace(name)
	desc, _ = tool["description"].(string)
	if desc == "" {
		desc, _ = fn["description"].(string)
	}
	desc = strings.TrimSpace(desc)
	schema = tool["input_schema"]
	if schema == nil {
		schema = tool["parameters"]
	}
	if schema == nil {
		schema = fn["input_schema"]
	}
	if schema == nil {
		schema = fn["parameters"]
	}
	if schema == nil {
		schema = map[string]any{}
	}
	return name, desc, schema
}

// MergeSystem system 合并工具提示（对等 merge_system）。
func MergeSystem(system any, extra string) any {
	if extra == "" {
		return system
	}
	if s, ok := system.(string); ok && strings.TrimSpace(s) != "" {
		return strings.TrimSpace(s) + "\n\n" + extra
	}
	if arr, ok := system.([]any); ok {
		return append(append([]any{}, arr...), map[string]any{"type": "text", "text": extra})
	}
	return extra
}

// PreprocessMessages 消息预处理（对等 preprocess_messages）：
// tool_use/tool_result 转文本 XML，其余保留。
func PreprocessMessages(messages []any) []map[string]any {
	var out []map[string]any
	for _, m := range messages {
		mm, ok := m.(map[string]any)
		if !ok {
			continue
		}
		item := map[string]any{}
		for k, v := range mm {
			item[k] = v
		}
		switch content := item["content"].(type) {
		case string:
			item["content"] = content
		case []any:
			blocks := make([]any, 0, len(content))
			for _, b := range content {
				blocks = append(blocks, preprocessBlock(b))
			}
			item["content"] = blocks
		}
		out = append(out, item)
	}
	return out
}

func preprocessBlock(block any) any {
	bm, ok := block.(map[string]any)
	if !ok {
		return block
	}
	switch bm["type"] {
	case "tool_use":
		name, _ := bm["name"].(string)
		inputJSON, _ := json.Marshal(bm["input"])
		if string(inputJSON) == "null" {
			inputJSON = []byte("{}")
		}
		return map[string]any{"type": "text", "text": "<tool_calls><tool_call><tool_name>" + name + "</tool_name><parameters>" + string(inputJSON) + "</parameters></tool_call></tool_calls>"}
	case "tool_result":
		id, _ := bm["tool_use_id"].(string)
		var contentStr string
		switch c := bm["content"].(type) {
		case string:
			contentStr = c
		default:
			b, _ := json.Marshal(c)
			contentStr = string(b)
		}
		return map[string]any{"type": "text", "text": "Tool result " + id + ": " + contentStr}
	default:
		return block
	}
}

// MessageRequestFromBody 请求解析（对等 message_request）。
func MessageRequestFromBody(body map[string]any) MessageRequest {
	var rawMsgs []any
	if arr, ok := body["messages"].([]any); ok {
		rawMsgs = arr
	}
	tools, _ := body["tools"].([]any)
	system := MergeSystem(body["system"], BuildToolPrompt(tools))
	messages := PreprocessMessages(rawMsgs)
	model, _ := body["model"].(string)
	if strings.TrimSpace(model) == "" {
		model = "auto"
	}
	return MessageRequest{Messages: NormalizeTextMessages(messages), Model: strings.TrimSpace(model), Tools: tools, System: system}
}

// MessageResponse 非流式响应（对等 message_response）。
func MessageResponse(model, text string, inputTokens, outputTokens int, tools []any) map[string]any {
	content, stopReason := ContentBlocks(text, tools)
	return map[string]any{
		"id":            "msg_" + uuid.NewString(),
		"type":          "message",
		"role":          "assistant",
		"model":         model,
		"content":       content,
		"stop_reason":   stopReason,
		"stop_sequence": nil,
		"usage":         map[string]any{"input_tokens": inputTokens, "output_tokens": outputTokens},
	}
}

// ContentBlocks 文本 → content blocks + stop_reason（对等 content_blocks）。
func ContentBlocks(text string, tools []any) ([]any, string) {
	var calls [][2]any
	if len(tools) > 0 {
		calls = ParseToolCalls(text)
	}
	text = StripToolMarkup(text)
	if len(calls) > 0 {
		var content []any
		if text != "" {
			content = append(content, map[string]any{"type": "text", "text": text})
		}
		for _, c := range calls {
			name, _ := c[0].(string)
			content = append(content, map[string]any{
				"type": "tool_use", "id": "toolu_" + uuid.NewString(),
				"name": name, "input": c[1],
			})
		}
		return content, "tool_use"
	}
	return []any{map[string]any{"type": "text", "text": text}}, "end_turn"
}

var (
	toolMarkupRe = regexp.MustCompile(`(?is)<tool_calls\b[^>]*>.*?</tool_calls>|<tool_call\b[^>]*>.*?</tool_call>|<function_call\b[^>]*>.*?</function_call>|<invoke\b[^>]*>.*?</invoke>`)
	toolStartRe  = regexp.MustCompile(`(?is)<tool_calls\b|<tool_call\b|<function_call\b|<invoke\b`)
	codeFenceRe  = regexp.MustCompile(`(?is)` + "```.*?```")
	toolCallRe   = regexp.MustCompile(`(?is)<tool_call\b[^>]*>(.*?)</tool_call>|<function_call\b[^>]*>(.*?)</function_call>|<invoke\b[^>]*>(.*?)</invoke>`)
)

// StripToolMarkup 去除 XML 工具标记（对等 strip_tool_markup）。
func StripToolMarkup(text string) string {
	return strings.TrimSpace(toolMarkupRe.ReplaceAllString(text, ""))
}

// StreamableText 可流部分（遇到工具标记截断，对等 streamable_text）。
func StreamableText(text string) string {
	if loc := toolStartRe.FindStringIndex(text); loc != nil {
		return strings.TrimRight(text[:loc[0]], " \t\n")
	}
	return text
}

// ParseToolCalls 解析 XML tool_calls（对等 parse_tool_calls）。
func ParseToolCalls(text string) [][2]any {
	text = strings.TrimSpace(codeFenceRe.ReplaceAllString(text, ""))
	var out [][2]any
	for _, match := range toolCallRe.FindAllStringSubmatch(text, -1) {
		block := ""
		for _, part := range match[1:] {
			if part != "" {
				block = part
				break
			}
		}
		name := xmlValue(block, "tool_name")
		if name == "" {
			name = xmlValue(block, "name")
		}
		if name == "" {
			name = xmlValue(block, "function")
		}
		params := xmlValue(block, "parameters")
		if params == "" {
			params = xmlValue(block, "input")
		}
		if params == "" {
			params = xmlValue(block, "arguments")
		}
		if params == "" {
			params = "{}"
		}
		if name != "" {
			out = append(out, [2]any{name, parseToolParams(params)})
		}
	}
	return out
}

// xmlValue 取 XML 标签值（含 CDATA + html 反转义，对等 xml_value）。
func xmlValue(text, tag string) string {
	re := regexp.MustCompile(`(?is)<` + tag + `\b[^>]*>(.*?)</` + tag + `>`)
	m := re.FindStringSubmatch(text)
	if m == nil {
		return ""
	}
	value := strings.TrimSpace(m[1])
	cdataRe := regexp.MustCompile(`(?is)^<!\[CDATA\[(.*?)]]>$`)
	if cm := cdataRe.FindStringSubmatch(value); cm != nil {
		value = cm[1]
	}
	return strings.TrimSpace(html.UnescapeString(value))
}

// parseToolParams 参数解析（JSON 优先，失败按 XML 子标签，对等 parse_tool_params）。
func parseToolParams(raw string) map[string]any {
	raw = strings.TrimSpace(raw)
	var parsed map[string]any
	if err := json.Unmarshal([]byte(raw), &parsed); err == nil && parsed != nil {
		return parsed
	}
	out := map[string]any{}
	// RE2 无反向引用：手动配对 <tag>…</tag>
	tagOpenRe := regexp.MustCompile(`(?is)<([\w.\-]+)\b[^>]*>`)
	rest := raw
	for {
		loc := tagOpenRe.FindStringSubmatchIndex(rest)
		if loc == nil {
			break
		}
		tag := rest[loc[2]:loc[3]]
		after := rest[loc[1]:]
		closeTag := "</" + tag + ">"
		idx := strings.Index(strings.ToLower(after), strings.ToLower(closeTag))
		if idx < 0 {
			break
		}
		out[tag] = parseToolValue(after[:idx])
		rest = after[idx+len(closeTag):]
	}
	return out
}

func parseToolValue(raw string) any {
	value := xmlValue("<x>"+raw+"</x>", "x")
	var v any
	if err := json.Unmarshal([]byte(value), &v); err == nil {
		return v
	}
	return value
}

// AnthropicEvent SSE 事件（type + payload）。
type AnthropicEvent struct {
	Type    string
	Payload map[string]any
}

// StreamAnthropicEvents anthropic 流事件序列（对等 stream_events）。
// chunks 为 chat chunk 序列（CompletionChunk 形状），inputTokens 预计算。
func StreamAnthropicEvents(chunks []map[string]any, model string, inputTokens int, tools []any) []AnthropicEvent {
	messageID := "msg_" + uuid.NewString()
	created := time.Now().Unix()
	_ = created
	events := []AnthropicEvent{
		{Type: "message_start", Payload: map[string]any{"message": map[string]any{
			"id": messageID, "type": "message", "role": "assistant", "model": model,
			"content": []any{}, "stop_reason": nil, "stop_sequence": nil,
			"usage": map[string]any{"input_tokens": inputTokens, "output_tokens": 0},
		}}},
	}
	toolMode := len(tools) > 0
	textOpen := false
	if !toolMode {
		textOpen = true
		events = append(events, AnthropicEvent{Type: "content_block_start", Payload: map[string]any{
			"index": 0, "content_block": map[string]any{"type": "text", "text": ""},
		}})
	}
	current, streamed := "", ""
	toolStarted := false
	finishReason := ""
	for _, chunk := range chunks {
		choices, _ := chunk["choices"].([]any)
		if len(choices) == 0 {
			continue
		}
		first, _ := choices[0].(map[string]any)
		if first == nil {
			continue
		}
		if fr, _ := first["finish_reason"].(string); fr != "" {
			finishReason = fr
		}
		delta, _ := first["delta"].(map[string]any)
		if delta == nil {
			continue
		}
		textDelta, _ := delta["content"].(string)
		if textDelta == "" {
			continue
		}
		current += textDelta
		if !toolStarted {
			visible := current
			if toolMode {
				visible = StreamableText(current)
			}
			if strings.HasPrefix(visible, streamed) {
				d := visible[len(streamed):]
				if d != "" {
					if !textOpen {
						textOpen = true
						events = append(events, AnthropicEvent{Type: "content_block_start", Payload: map[string]any{
							"index": 0, "content_block": map[string]any{"type": "text", "text": ""},
						}})
					}
					streamed = visible
					events = append(events, AnthropicEvent{Type: "content_block_delta", Payload: map[string]any{
						"index": 0, "delta": map[string]any{"type": "text_delta", "text": d},
					}})
				}
			}
			toolStarted = toolMode && visible != current
		}
		_ = finishReason
	}
	content, stopReason := ContentBlocks(current, tools)
	if textOpen {
		events = append(events, AnthropicEvent{Type: "content_block_stop", Payload: map[string]any{"index": 0}})
	}
	if stopReason == "tool_use" {
		startIndex := 0
		if textOpen {
			startIndex = 1
		}
		// 文本残留补发
		if len(content) > 0 {
			if first, ok := content[0].(map[string]any); ok && first["type"] == "text" {
				remaining, _ := first["text"].(string)
				if strings.HasPrefix(remaining, streamed) {
					remaining = remaining[len(streamed):]
				}
				if remaining != "" {
					if !textOpen {
						events = append(events, AnthropicEvent{Type: "content_block_start", Payload: map[string]any{
							"index": 0, "content_block": map[string]any{"type": "text", "text": ""},
						}})
					}
					events = append(events, AnthropicEvent{Type: "content_block_delta", Payload: map[string]any{
						"index": 0, "delta": map[string]any{"type": "text_delta", "text": remaining},
					}})
					if !textOpen {
						events = append(events, AnthropicEvent{Type: "content_block_stop", Payload: map[string]any{"index": 0}})
					}
				}
				startIndex = 1
				content = content[1:]
			}
		}
		events = append(events, streamBufferedBlocks(content, startIndex)...)
	}
	events = append(events, AnthropicEvent{Type: "message_delta", Payload: map[string]any{
		"delta": map[string]any{"stop_reason": stopReason, "stop_sequence": nil},
		"usage": map[string]any{"output_tokens": utils.CountTokens(current)},
	}})
	events = append(events, AnthropicEvent{Type: "message_stop", Payload: map[string]any{}})
	return events
}

// streamBufferedBlocks 缓冲块补发（对等 _stream_buffered_blocks）。
func streamBufferedBlocks(content []any, startIndex int) []AnthropicEvent {
	var events []AnthropicEvent
	for offset, block := range content {
		bm, _ := block.(map[string]any)
		if bm == nil {
			continue
		}
		index := startIndex + offset
		var start, delta map[string]any
		if bm["type"] == "tool_use" {
			start = map[string]any{"type": "tool_use", "id": bm["id"], "name": bm["name"], "input": map[string]any{}}
			inputJSON, _ := json.Marshal(bm["input"])
			if string(inputJSON) == "null" {
				inputJSON = []byte("{}")
			}
			delta = map[string]any{"type": "input_json_delta", "partial_json": string(inputJSON)}
		} else {
			text, _ := bm["text"].(string)
			start = map[string]any{"type": "text", "text": ""}
			delta = map[string]any{"type": "text_delta", "text": text}
		}
		events = append(events,
			AnthropicEvent{Type: "content_block_start", Payload: map[string]any{"index": index, "content_block": start}},
			AnthropicEvent{Type: "content_block_delta", Payload: map[string]any{"index": index, "delta": delta}},
			AnthropicEvent{Type: "content_block_stop", Payload: map[string]any{"index": index}},
		)
	}
	return events
}

// CollectAnthropicText 聚合 anthropic 事件为响应体（非流式用；对等 handle 非流分支）。
func CollectAnthropicText(events []AnthropicEvent) (text string) {
	for _, ev := range events {
		if ev.Type != "content_block_delta" {
			continue
		}
		delta, _ := ev.Payload["delta"].(map[string]any)
		if delta == nil || delta["type"] != "text_delta" {
			continue
		}
		if s, ok := delta["text"].(string); ok {
			text += s
		}
	}
	return text
}

// StreamAnthropicText 全流程：orch 文本流 → chat chunks → anthropic 事件（供 handler 调用）。
func StreamAnthropicText(ctx context.Context, orch *Orchestrator, req MessageRequest) ([]AnthropicEvent, error) {
	var chunks []map[string]any
	text, _, err := orch.StreamText(ctx, TextRequest{Messages: req.Messages, Model: req.Model}, func(delta string) {
		chunks = append(chunks, CompletionChunk(req.Model, map[string]any{"content": delta}, "", "", 0))
	})
	if err != nil {
		return nil, err
	}
	if text == "" {
		// 空文本也需要 finish 帧
		chunks = append(chunks, CompletionChunk(req.Model, map[string]any{}, "stop", "", 0))
	}
	inputTokens := countTextTokensOf(req.Messages)
	return StreamAnthropicEvents(chunks, req.Model, inputTokens, req.Tools), nil
}
