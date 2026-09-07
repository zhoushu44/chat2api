package protocol

import "testing"

// TestBuildToolPrompt P2.3：工具提示块。
func TestBuildToolPrompt(t *testing.T) {
	if got := BuildToolPrompt(nil); got != "" {
		t.Fatalf("nil tools=%q", got)
	}
	got := BuildToolPrompt([]any{
		map[string]any{"name": "read", "description": "read file", "input_schema": map[string]any{"type": "object"}},
	})
	if !containsStr(got, "Tool: read") || !containsStr(got, "Available tools:") {
		t.Fatalf("tool prompt=%q", got)
	}
}

// TestMergeSystem P2.3：system 合并。
func TestMergeSystem(t *testing.T) {
	if got := MergeSystem("base", ""); got != "base" {
		t.Fatalf("empty extra=%v", got)
	}
	if got := MergeSystem("base", "extra"); got != "base\n\nextra" {
		t.Fatalf("string merge=%v", got)
	}
	merged := MergeSystem([]any{map[string]any{"type": "text", "text": "a"}}, "extra")
	arr, _ := merged.([]any)
	if len(arr) != 2 {
		t.Fatalf("list merge=%v", merged)
	}
}

// TestPreprocessMessages P2.3：tool_use/tool_result 转文本。
func TestPreprocessMessages(t *testing.T) {
	out := PreprocessMessages([]any{
		map[string]any{"role": "user", "content": []any{
			map[string]any{"type": "text", "text": "hi"},
			map[string]any{"type": "tool_use", "name": "read", "input": map[string]any{"path": "a"}},
			map[string]any{"type": "tool_result", "tool_use_id": "t1", "content": "ok"},
		}},
	})
	if len(out) != 1 {
		t.Fatalf("len=%d", len(out))
	}
	blocks, _ := out[0]["content"].([]any)
	if len(blocks) != 3 {
		t.Fatalf("blocks=%v", out[0]["content"])
	}
	if b1, _ := blocks[1].(map[string]any); b1["type"] != "text" || !containsStr(b1["text"].(string), "<tool_call") {
		t.Fatalf("tool_use not converted: %v", blocks[1])
	}
}

// TestContentBlocksStopReason P2.3：stop_reason 映射。
func TestContentBlocksStopReason(t *testing.T) {
	content, reason := ContentBlocks("plain text", nil)
	if reason != "end_turn" || len(content) != 1 {
		t.Fatalf("plain: %v %s", content, reason)
	}
	tools := []any{map[string]any{"name": "read"}}
	content, reason = ContentBlocks(`<tool_call><tool_name>read</tool_name><parameters>{"path":"a"}</parameters></tool_call>`, tools)
	if reason != "tool_use" {
		t.Fatalf("tool reason=%s", reason)
	}
	found := false
	for _, c := range content {
		if m, ok := c.(map[string]any); ok && m["type"] == "tool_use" {
			found = true
			if m["name"] != "read" {
				t.Fatalf("tool name=%v", m)
			}
		}
	}
	if !found {
		t.Fatalf("tool_use block missing: %v", content)
	}
}

// TestParseToolCallsCDATA P2.3：CDATA + html 反转义。
func TestParseToolCallsCDATA(t *testing.T) {
	calls := ParseToolCalls(`<tool_call><tool_name>run</tool_name><parameters><cmd><![CDATA[echo &amp; hi]]></cmd></parameters></tool_call>`)
	if len(calls) != 1 || calls[0][0] != "run" {
		t.Fatalf("calls=%v", calls)
	}
	params, _ := calls[0][1].(map[string]any)
	// parseToolParams 对 <cmd>…</cmd> 子标签解析
	if params["cmd"] != "echo & hi" {
		t.Fatalf("cdata params=%v", params)
	}
}

// TestStreamableTextCut P2.3：工具标记处截断。
func TestStreamableTextCut(t *testing.T) {
	if got := StreamableText("hello <tool_call>"); got != "hello" {
		t.Fatalf("cut=%q", got)
	}
	if got := StreamableText("plain"); got != "plain" {
		t.Fatalf("plain=%q", got)
	}
}

// TestMessageResponseShape P2.3：响应体形状。
func TestMessageResponseShape(t *testing.T) {
	resp := MessageResponse("claude", "hi", 10, 2, nil)
	if resp["type"] != "message" || resp["role"] != "assistant" || resp["stop_reason"] != "end_turn" {
		t.Fatalf("resp=%v", resp)
	}
	usage, _ := resp["usage"].(map[string]any)
	if usage["input_tokens"] != 10 || usage["output_tokens"] != 2 {
		t.Fatalf("usage=%v", usage)
	}
	content, _ := resp["content"].([]any)
	if len(content) != 1 {
		t.Fatalf("content=%v", resp["content"])
	}
}

// TestStreamAnthropicEventsShape P2.3：事件序列形状。
func TestStreamAnthropicEventsShape(t *testing.T) {
	chunks := []map[string]any{
		CompletionChunk("m", map[string]any{"content": "Hel"}, "", "id", 0),
		CompletionChunk("m", map[string]any{"content": "lo"}, "", "id", 0),
		CompletionChunk("m", map[string]any{}, "stop", "id", 0),
	}
	events := StreamAnthropicEvents(chunks, "claude", 5, nil)
	wantTypes := []string{"message_start", "content_block_start", "content_block_delta", "content_block_delta", "content_block_stop", "message_delta", "message_stop"}
	if len(events) != len(wantTypes) {
		t.Fatalf("events=%d want %d", len(events), len(wantTypes))
	}
	for i, want := range wantTypes {
		if events[i].Type != want {
			t.Fatalf("event[%d]=%s want %s", i, events[i].Type, want)
		}
	}
	if text := CollectAnthropicText(events); text != "Hello" {
		t.Fatalf("collect=%q", text)
	}
	// tool_use 模式：stop_reason tool_use + buffered blocks
	chunks2 := []map[string]any{
		CompletionChunk("m", map[string]any{"content": `<tool_call><tool_name>r</tool_name><parameters>{"a":1}</parameters></tool_call>`}, "", "id", 0),
		CompletionChunk("m", map[string]any{}, "stop", "id", 0),
	}
	events2 := StreamAnthropicEvents(chunks2, "claude", 5, []any{map[string]any{"name": "r"}})
	lastDelta := ""
	for _, ev := range events2 {
		if ev.Type == "message_delta" {
			if d, ok := ev.Payload["delta"].(map[string]any); ok {
				lastDelta, _ = d["stop_reason"].(string)
			}
		}
	}
	if lastDelta != "tool_use" {
		t.Fatalf("tool stop_reason=%q", lastDelta)
	}
}

func containsStr(s, sub string) bool {
	return len(s) >= len(sub) && (func() bool {
		for i := 0; i+len(sub) <= len(s); i++ {
			if s[i:i+len(sub)] == sub {
				return true
			}
		}
		return false
	})()
}
