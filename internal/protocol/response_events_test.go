package protocol

import (
	"context"
	"testing"

	"chatgpt2api/internal/account"
)

// TestMessagesFromInput P2.2：input 三形态解析。
func TestMessagesFromInput(t *testing.T) {
	// string
	msgs := MessagesFromInput("hello", "")
	if len(msgs) != 1 || msgs[0]["role"] != "user" {
		t.Fatalf("string: %v", msgs)
	}
	// instructions → system 首条
	msgs = MessagesFromInput("hello", "be nice")
	if len(msgs) != 2 || msgs[0]["role"] != "system" {
		t.Fatalf("instructions: %v", msgs)
	}
	// list of role items
	msgs = MessagesFromInput([]any{
		map[string]any{"role": "user", "content": "hi"},
		map[string]any{"role": "assistant", "content": "yo"},
	}, "")
	if len(msgs) != 2 {
		t.Fatalf("list: %v", msgs)
	}
	// content parts 列表
	msgs = MessagesFromInput([]any{
		map[string]any{"type": "input_text", "text": "describe"},
	}, "")
	if len(msgs) != 1 || msgs[0]["role"] != "user" {
		t.Fatalf("parts: %v", msgs)
	}
	// 空 input
	if msgs := MessagesFromInput("", ""); len(msgs) != 0 {
		t.Fatalf("empty: %v", msgs)
	}
}

// TestResponseFraming P2.2：帧构造 + collect。
func TestResponseFraming(t *testing.T) {
	created := ResponseCreated("resp_1", "gpt-4o", 123)
	resp, _ := created["response"].(map[string]any)
	if created["type"] != "response.created" || resp["status"] != "in_progress" {
		t.Fatalf("created: %v", created)
	}
	item := TextOutputItem("hi", "msg_1", "completed")
	content, _ := item["content"].([]any)
	if item["type"] != "message" || len(content) != 1 {
		t.Fatalf("item: %v", item)
	}
	comp := ResponseCompleted("resp_1", "gpt-4o", 123, []any{item}, ResponseUsage(10, 0, 5))
	usage, _ := comp["response"].(map[string]any)["usage"].(map[string]any)
	if usage["input_tokens"] != 10 || usage["output_tokens"] != 5 || usage["total_tokens"] != 15 {
		t.Fatalf("usage: %v", usage)
	}
	got, err := CollectResponse([]ResponseEvent{
		{Type: "response.created", Payload: created},
		{Type: "response.completed", Payload: comp},
	})
	if err != nil || got["id"] != "resp_1" {
		t.Fatalf("collect: %v %v", got, err)
	}
	if _, err := CollectResponse(nil); err == nil {
		t.Fatal("empty collect should error")
	}
	// 图片条目：b64 入选，空跳过
	items := ImageOutputItems("a cat", []map[string]string{
		{"b64_json": "AAA", "revised_prompt": ""},
		{"b64_json": "", "revised_prompt": "x"},
	})
	if len(items) != 1 {
		t.Fatalf("image items=%d", len(items))
	}
	first, _ := items[0].(map[string]any)
	if first["type"] != "image_generation_call" || first["result"] != "AAA" || first["revised_prompt"] != "a cat" {
		t.Fatalf("image item: %v", first)
	}
}

// TestExtractResponsePrompt P2.2：prompt 提取。
func TestExtractResponsePrompt(t *testing.T) {
	if got := ExtractResponsePrompt("draw a cat"); got != "draw a cat" {
		t.Fatalf("string=%q", got)
	}
	got := ExtractResponsePrompt([]any{
		map[string]any{"type": "input_text", "text": "draw"},
		map[string]any{"type": "input_text", "text": "a cat"},
	})
	if got != "draw\na cat" {
		t.Fatalf("list=%q", got)
	}
}

// TestStreamTextResponseEventsSequence P2.2：文本事件序列形状（mock orch）。
func TestStreamTextResponseEventsSequence(t *testing.T) {
	pool := account.NewPool(nil, 0)
	orch := NewOrchestrator(pool)
	// 无账号 → 错误（事件序列构造前置失败）
	_, err := StreamTextResponseEvents(context.Background(), orch, "auto",
		[]map[string]any{{"role": "user", "content": "hi"}}, "")
	if err == nil {
		t.Fatal("no account should error")
	}
}
