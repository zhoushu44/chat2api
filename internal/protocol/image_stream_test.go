package protocol

import (
	"context"
	"testing"

	"chatgpt2api/internal/account"
)

// TestImageOutputChunk P2.4：三态 ToChunk 形状对齐 Python to_chunk。
func TestImageOutputChunk(t *testing.T) {
	prog := ImageOutput{Kind: ImageOutputProgress, Model: "m", Index: 0, Total: 3, Text: "uploading", Created: 1}
	c := prog.ToChunk()
	if c["object"] != "image.generation.chunk" || c["progress_text"] != "uploading" {
		t.Fatalf("progress chunk=%v", c)
	}
	msg := ImageOutput{Kind: ImageOutputMessage, Text: "oops", Created: 1}
	cm := msg.ToChunk()
	if cm["object"] != "image.generation.message" || cm["message"] != "oops" {
		t.Fatalf("message chunk=%v", cm)
	}
	if _, ok := cm["progress_text"]; ok {
		t.Fatal("message chunk should drop progress_text")
	}
	res := ImageOutput{Kind: ImageOutputResult, Data: []map[string]string{{"b64_json": "AAA"}}, Created: 1}
	cr := res.ToChunk()
	if cr["object"] != "image.generation.result" {
		t.Fatalf("result chunk=%v", cr)
	}
	data, _ := cr["data"].([]any)
	if len(data) != 1 {
		t.Fatalf("result data=%v", cr["data"])
	}
}

// TestBuildImagePrompt 对等 Python build_image_prompt：size/quality hint 拼接。
func TestBuildImagePrompt(t *testing.T) {
	if got := BuildImagePrompt("a cat", "", ""); got != "a cat" {
		t.Fatalf("empty hints should passthrough: %q", got)
	}
	if got := BuildImagePrompt("a cat", "1024x1024", "auto"); got != "a cat\n\n输出图片尺寸为 1024x1024。输出图片质量为 auto。" {
		t.Fatalf("hints: %q", got)
	}
	if got := BuildImagePrompt("  a cat  ", "", "hd"); got != "a cat\n\n输出图片质量为 hd。" {
		t.Fatalf("trim: %q", got)
	}
}

// TestWarmupEmptyPool OPT-6：空池预热返回 0，不报错。
func TestWarmupEmptyPool(t *testing.T) {
	orch := NewOrchestrator(account.NewPool(nil, 0))
	if n := orch.Warmup(context.Background()); n != 0 {
		t.Fatalf("warmed=%d want 0", n)
	}
	var nilOrch *Orchestrator
	if n := nilOrch.Warmup(context.Background()); n != 0 {
		t.Fatalf("nil orch warmed=%d want 0", n)
	}
}

// TestHistoryMessagesSkip P2.4：历史回显命中即跳过。
func TestHistoryMessagesSkip(t *testing.T) {
	p := NewTextStreamParserWithHistory("", []string{"old answer"})
	// 历史回放帧：命中 histMsgs[0] → 跳过无增量
	if d := p.Feed(`{"message":{"author":{"role":"assistant"},"content":{"content_type":"text","parts":["old answer"]}}}`); d != "" {
		t.Fatalf("history replay should be skipped, got %q", d)
	}
	// 之后的新文本：状态已重置，全量即增量（对等 Python continue 后下帧行为）
	if d := p.Feed(`{"message":{"author":{"role":"assistant"},"content":{"content_type":"text","parts":["old answernew"]}}}`); d != "old answernew" {
		t.Fatalf("post-history delta=%q", d)
	}
	// 再来增量：前缀差分
	if d := p.Feed(`{"message":{"author":{"role":"assistant"},"content":{"content_type":"text","parts":["old answernew!"]}}}`); d != "!" {
		t.Fatalf("continued delta=%q", d)
	}
}

// TestNormalizeDedup P2.4：相邻重复去重（Python 默认 drop_adjacent_duplicates=True）。
func TestNormalizeDedup(t *testing.T) {
	msgs := NormalizeTextMessages([]map[string]any{
		{"role": "user", "content": "hi"},
		{"role": "user", "content": "hi"},
		{"role": "assistant", "content": "yo"},
		{"role": "assistant", "content": "yo"},
		{"role": "user", "content": "hi"},
	})
	if len(msgs) != 3 {
		t.Fatalf("dedup len=%d want 3: %v", len(msgs), msgs)
	}
	// 非相邻重复保留
	if msgs[2]["content"] != "hi" {
		t.Fatalf("non-adjacent dup dropped: %v", msgs)
	}
}

// TestGenerateStreamNoAccount P2.4：无账号错误。
func TestGenerateStreamNoAccount(t *testing.T) {
	pool := account.NewPool(nil, 0)
	orch := NewOrchestrator(pool)
	var kinds []ImageOutputKind
	_, err := orch.GenerateStream(context.Background(), GenerateRequest{Prompt: "x"}, func(o ImageOutput) {
		kinds = append(kinds, o.Kind)
	})
	if err == nil {
		t.Fatal("no account should error")
	}
}
