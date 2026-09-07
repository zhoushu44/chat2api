package protocol

import "testing"

// TestTextParserMessageDeltas P2.1 验收：message 增量解析（前缀差分）。
func TestTextParserMessageDeltas(t *testing.T) {
	p := NewTextStreamParser("")
	if d := p.Feed(`{"message":{"author":{"role":"assistant"},"content":{"content_type":"text","parts":["Hello"]}}}`); d != "Hello" {
		t.Fatalf("delta=%q", d)
	}
	if d := p.Feed(`{"message":{"author":{"role":"assistant"},"content":{"content_type":"text","parts":["Hello world"]}}}`); d != " world" {
		t.Fatalf("delta=%q", d)
	}
	if p.Text != "Hello world" {
		t.Fatalf("text=%q", p.Text)
	}
}

// TestTextParserPatchOps P2.1：patch op（append/replace）解析。
// 真实上游 patch 事件带 p 路径（{"p":"/message/content/parts/0","o":"append","v":...}）。
func TestTextParserPatchOps(t *testing.T) {
	p := NewTextStreamParser("")
	ev1 := `{"p":"/message/content/parts/0","o":"append","v":"foo"}`
	if d := p.Feed(ev1); d != "foo" {
		t.Fatalf("append=%q", d)
	}
	ev2 := `{"p":"/message/content/parts/0","o":"append","v":"bar"}`
	if d := p.Feed(ev2); d != "bar" {
		t.Fatalf("append2=%q", d)
	}
	if p.Text != "foobar" {
		t.Fatalf("text=%q", p.Text)
	}
	if d := p.Feed(`{"p":"/message/content/parts/0","o":"replace","v":"new"}`); d == "" {
		// replace 从当前文本重置（非前缀延续 → 全量）
		t.Logf("replace delta=%q", d)
	}
}

// TestTextParserDone P2.1：[DONE] 终止。
func TestTextParserDone(t *testing.T) {
	p := NewTextStreamParser("")
	p.Feed(`{"message":{"author":{"role":"assistant"},"content":{"content_type":"text","parts":["x"]}}}`)
	if d := p.Feed("[DONE]"); d != "" || !p.Finished {
		t.Fatalf("done handling broken: %q %v", d, p.Finished)
	}
}

// TestTextParserHistoryStrip P2.1：历史回显剥离。
func TestTextParserHistoryStrip(t *testing.T) {
	p := NewTextStreamParser("old answer")
	if d := p.Feed(`{"message":{"author":{"role":"assistant"},"content":{"content_type":"text","parts":["old answernew"]}}}`); d != "new" {
		t.Fatalf("history strip delta=%q", d)
	}
}

// TestSanitizeAnnotations P2.1：私用区标注净化。
func TestSanitizeAnnotations(t *testing.T) {
	in := "see \uE200url\uE202OpenAI\uE202https://openai.com\uE201 now"
	got := SanitizeOutputText(in)
	if got != "see OpenAI (https://openai.com) now" {
		t.Fatalf("sanitize=%q", got)
	}
	in2 := "text\uE200cite\uE202turn0search1\uE202Paris\uE201!"
	if got2 := SanitizeOutputText(in2); got2 != "textParis!" {
		t.Fatalf("cite sanitize=%q", got2)
	}
}

// TestChatFraming P2.1：帧构造 + usage + 请求解析。
func TestChatFraming(t *testing.T) {
	chunk := CompletionChunk("gpt-4o", map[string]any{"role": "assistant", "content": "hi"}, "", "chatcmpl-1", 123)
	choices, _ := chunk["choices"].([]any)
	if len(choices) != 1 {
		t.Fatal("chunk shape")
	}
	if chunk["object"] != "chat.completion.chunk" || chunk["id"] != "chatcmpl-1" {
		t.Fatalf("chunk meta: %v", chunk)
	}
	resp := CompletionResponse("gpt-4o", "hello", []map[string]any{{"role": "user", "content": "hi"}})
	if resp["object"] != "chat.completion" {
		t.Fatalf("response object: %v", resp)
	}
	usage, _ := resp["usage"].(map[string]any)
	if usage["total_tokens"] == nil || usage["prompt_tokens"] == nil {
		t.Fatalf("usage block: %v", usage)
	}
	// prompt 字符串兜底
	msgs, err := ChatMessagesFromBody(map[string]any{"prompt": "hello"})
	if err != nil || len(msgs) != 1 || msgs[0]["role"] != "user" {
		t.Fatalf("prompt fallback: %v %v", msgs, err)
	}
	// 空请求 400 语义
	if _, err := ChatMessagesFromBody(map[string]any{}); err == nil {
		t.Fatal("empty body should error")
	}
	// thinking_effort 归一
	if got := ThinkingEffortFromBody(map[string]any{"reasoning_effort": "XHigh"}); got != "extended" {
		t.Fatalf("effort=%q", got)
	}
	if got := ThinkingEffortFromBody(map[string]any{"reasoning": map[string]any{"effort": "low"}}); got != "low" {
		t.Fatalf("effort2=%q", got)
	}
	// chunk 聚合
	agg := CollectChunks([]map[string]any{
		CompletionChunk("m", map[string]any{"content": "a"}, "", "id", 0),
		CompletionChunk("m", map[string]any{"content": "b"}, "", "id", 0),
	})
	if agg != "ab" {
		t.Fatalf("aggregate=%q", agg)
	}
}
