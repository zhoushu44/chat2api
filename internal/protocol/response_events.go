package protocol

import (
	"context"
	"fmt"
	"strings"
	"time"

	"chatgpt2api/internal/utils"

	"github.com/google/uuid"
)

// responses 事件流（P2.2）：对等 openai_v1_response.py。
// 文本路径事件序列：created → output_item.added → output_text.delta* →
// output_text.done → output_item.done → completed（含 usage）。
// 图片路径：created → output_item.done(image_generation_call)* → completed。

// RESPONSE_CONTENT_PART_TYPES 对等同名常量。
var ResponseContentPartTypes = map[string]bool{
	"text": true, "input_text": true, "output_text": true,
	"image_url": true, "input_image": true, "image": true,
}

// MessagesFromInput responses input → messages（对等 messages_from_input）。
// input 可为 string / dict / list；instructions 充当 system。
func MessagesFromInput(input any, instructions any) []map[string]any {
	var messages []map[string]any
	if s, ok := instructions.(string); ok && strings.TrimSpace(s) != "" {
		messages = append(messages, map[string]any{"role": "system", "content": strings.TrimSpace(s)})
	}
	switch v := input.(type) {
	case string:
		if strings.TrimSpace(v) != "" {
			messages = append(messages, map[string]any{"role": "user", "content": strings.TrimSpace(v)})
		}
		return messages
	case map[string]any:
		if isResponseContentPart(v) {
			messages = append(messages, map[string]any{"role": "user", "content": []any{v}})
			return messages
		}
		messages = append(messages, map[string]any{
			"role":    roleOr(v, "user"),
			"content": messageContentFromItem(v),
		})
		return messages
	case []any:
		allParts := true
		for _, item := range v {
			if m, ok := item.(map[string]any); !ok || !isResponseContentPart(m) {
				allParts = false
				break
			}
		}
		if allParts {
			messages = append(messages, map[string]any{"role": "user", "content": v})
			return messages
		}
		var pending []any
		flush := func() {
			if len(pending) > 0 {
				messages = append(messages, map[string]any{"role": "user", "content": pending})
				pending = nil
			}
		}
		for _, item := range v {
			if m, ok := item.(map[string]any); ok && isResponseContentPart(m) {
				pending = append(pending, m)
				continue
			}
			flush()
			if m, ok := item.(map[string]any); ok {
				messages = append(messages, map[string]any{
					"role":    roleOr(m, "user"),
					"content": messageContentFromItem(m),
				})
			}
		}
		flush()
		return messages
	default:
		return messages
	}
}

func roleOr(m map[string]any, def string) string {
	if r, _ := m["role"].(string); r != "" {
		return r
	}
	return def
}

func isResponseContentPart(v map[string]any) bool {
	t, _ := v["type"].(string)
	t = strings.TrimSpace(t)
	if ResponseContentPartTypes[t] {
		return true
	}
	if _, hasURL := v["image_url"]; hasURL && t != "message" {
		return true
	}
	return false
}

// messageContentFromItem 从 response item 取 content（对等 _message_content_from_response_item）。
func messageContentFromItem(item map[string]any) any {
	switch c := item["content"].(type) {
	case []any:
		return c
	case string:
		return c
	default:
		if s := ExtractResponsePrompt(item); s != "" {
			return s
		}
		if c != nil {
			return c
		}
		return ""
	}
}

// ExtractResponsePrompt 从 input 提取文本 prompt（对等 extract_response_prompt 简化版）。
func ExtractResponsePrompt(input any) string {
	var b strings.Builder
	var walk func(v any)
	walk = func(v any) {
		switch t := v.(type) {
		case string:
			b.WriteString(t)
			b.WriteString("\n")
		case map[string]any:
			if typ, _ := t["type"].(string); typ == "input_text" || typ == "text" || typ == "output_text" {
				if s, _ := t["text"].(string); s != "" {
					b.WriteString(s)
					b.WriteString("\n")
					return
				}
			}
			if s, _ := t["text"].(string); s != "" && (t["role"] != nil) {
				b.WriteString(s)
				b.WriteString("\n")
				return
			}
			for _, vv := range t {
				walk(vv)
			}
		case []any:
			for _, vv := range t {
				walk(vv)
			}
		}
	}
	walk(input)
	return strings.TrimSpace(b.String())
}

// TextOutputItem 文本输出条目（对等 text_output_item）。
func TextOutputItem(text, itemID, status string) map[string]any {
	if itemID == "" {
		itemID = "msg_" + uuid.NewString()
	}
	return map[string]any{
		"id":     itemID,
		"type":   "message",
		"status": status,
		"role":   "assistant",
		"content": []any{map[string]any{
			"type": "output_text", "text": text, "annotations": []any{},
		}},
	}
}

// ResponseCreated response.created 事件（对等）。
func ResponseCreated(responseID, model string, created int64) map[string]any {
	return map[string]any{
		"type": "response.created",
		"response": map[string]any{
			"id": responseID, "object": "response", "created_at": created,
			"status": "in_progress", "error": nil, "incomplete_details": nil,
			"model": model, "output": []any{}, "parallel_tool_calls": false,
		},
	}
}

// ResponseCompleted response.completed 事件（对等）。
func ResponseCompleted(responseID, model string, created int64, output []any, usage map[string]any) map[string]any {
	resp := map[string]any{
		"id": responseID, "object": "response", "created_at": created,
		"status": "completed", "error": nil, "incomplete_details": nil,
		"model": model, "output": output, "parallel_tool_calls": false,
	}
	if usage != nil {
		resp["usage"] = usage
	}
	return map[string]any{"type": "response.completed", "response": resp}
}

// ResponseUsage 文本 usage（对等 token_usage；token 用 utils 近似）。
func ResponseUsage(inputTextTokens, inputImageTokens, outputTextTokens int) map[string]any {
	return map[string]any{
		"input_tokens":  inputTextTokens + inputImageTokens,
		"output_tokens": outputTextTokens,
		"total_tokens":  inputTextTokens + inputImageTokens + outputTextTokens,
		"input_tokens_details": map[string]any{
			"text_tokens":  inputTextTokens,
			"image_tokens": inputImageTokens,
		},
		"output_tokens_details": map[string]any{"text_tokens": outputTextTokens},
	}
}

// ImageOutputItems 图片输出条目（对等 image_output_items；result 取 b64）。
func ImageOutputItems(prompt string, data []map[string]string) []any {
	var out []any
	for i, item := range data {
		b64 := strings.TrimSpace(item["b64_json"])
		if b64 == "" {
			continue
		}
		rev := strings.TrimSpace(item["revised_prompt"])
		if rev == "" {
			rev = prompt
		}
		out = append(out, map[string]any{
			"id":             fmt.Sprintf("ig_%d", i+1),
			"type":           "image_generation_call",
			"status":         "completed",
			"result":         b64,
			"revised_prompt": rev,
		})
	}
	return out
}

// ResponseEvent 单个 SSE 事件（type + payload）。
type ResponseEvent struct {
	Type    string
	Payload map[string]any
}

// StreamTextResponseEvents 文本 responses 事件序列（对等 stream_text_response）。
func StreamTextResponseEvents(ctx context.Context, orch *Orchestrator, model string, messages []map[string]any, effort string) ([]ResponseEvent, error) {
	responseID := "resp_" + uuid.NewString()
	itemID := "msg_" + uuid.NewString()
	created := time.Now().Unix()
	events := []ResponseEvent{
		{Type: "response.created", Payload: ResponseCreated(responseID, model, created)},
		{Type: "response.output_item.added", Payload: map[string]any{
			"output_index": 0, "item": TextOutputItem("", itemID, "in_progress"),
		}},
	}
	var full strings.Builder
	text, _, err := orch.StreamText(ctx, TextRequest{Messages: messages, Model: model, ThinkingEffort: effort}, func(delta string) {
		full.WriteString(delta)
		events = append(events, ResponseEvent{Type: "response.output_text.delta", Payload: map[string]any{
			"item_id": itemID, "output_index": 0, "content_index": 0, "delta": delta,
		}})
	})
	if err != nil {
		return nil, err
	}
	fullText := full.String()
	if fullText == "" {
		fullText = text
	}
	events = append(events, ResponseEvent{Type: "response.output_text.done", Payload: map[string]any{
		"item_id": itemID, "output_index": 0, "content_index": 0, "text": fullText,
	}})
	item := TextOutputItem(fullText, itemID, "completed")
	events = append(events, ResponseEvent{Type: "response.output_item.done", Payload: map[string]any{
		"output_index": 0, "item": item,
	}})
	usage := ResponseUsage(
		countTextTokensOf(messages),
		0,
		utils.CountTokens(fullText),
	)
	events = append(events, ResponseEvent{Type: "response.completed", Payload: ResponseCompleted(responseID, model, created, []any{item}, usage)})
	return events, nil
}

// StreamImageResponseEvents 图片 responses 事件序列（对等 stream_image_response）。
func StreamImageResponseEvents(ctx context.Context, orch *Orchestrator, prompt, model string) ([]ResponseEvent, error) {
	responseID := "resp_" + uuid.NewString()
	created := time.Now().Unix()
	res, err := orch.Generate(ctx, GenerateRequest{Prompt: prompt, Model: model, N: 1})
	if err != nil {
		return nil, err
	}
	data := make([]map[string]string, 0, len(res.B64)+len(res.URLs))
	for _, b := range res.B64 {
		data = append(data, map[string]string{"b64_json": string(b), "revised_prompt": prompt})
	}
	for _, u := range res.URLs {
		if len(data) == 0 {
			data = append(data, map[string]string{"url": u, "revised_prompt": prompt})
		}
	}
	events := []ResponseEvent{
		{Type: "response.created", Payload: ResponseCreated(responseID, model, created)},
	}
	items := ImageOutputItems(prompt, data)
	if len(items) == 0 {
		return nil, fmt.Errorf("upstream returned no images")
	}
	usage := ResponseUsage(utils.CountTokens(prompt), 0, utils.CountTokens(prompt))
	for i, item := range items {
		events = append(events, ResponseEvent{Type: "response.output_item.done", Payload: map[string]any{
			"output_index": i, "item": item,
		}})
	}
	events = append(events, ResponseEvent{Type: "response.completed", Payload: ResponseCompleted(responseID, model, created, items, usage)})
	return events, nil
}

// CollectResponse 取 completed 事件的 response（对等 collect_response）。
func CollectResponse(events []ResponseEvent) (map[string]any, error) {
	for _, ev := range events {
		if ev.Type == "response.completed" {
			if resp, ok := ev.Payload["response"].(map[string]any); ok && len(resp) > 0 {
				return resp, nil
			}
		}
	}
	return nil, fmt.Errorf("response generation failed")
}

func countTextTokensOf(messages []map[string]any) int {
	total := 0
	for _, m := range messages {
		total += utils.CountTokens(MessageText(m["content"]))
	}
	return total
}
