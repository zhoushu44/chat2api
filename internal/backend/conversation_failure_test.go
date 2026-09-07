package backend

import (
	"context"
	"strings"
	"testing"
	"time"
)

func TestClassifyConversationFailureTextReply(t *testing.T) {
	raw := map[string]any{"mapping": map[string]any{
		"u1": map[string]any{"message": map[string]any{
			"id": "u1", "author": map[string]any{"role": "user"},
			"create_time": 100.0,
			"content":     map[string]any{"content_type": "text", "parts": []any{"draw a cat"}},
		}},
		"a1": map[string]any{"message": map[string]any{
			"id": "a1", "author": map[string]any{"role": "assistant"},
			"create_time": 101.0, "status": "finished_successfully", "end_turn": true,
			"content": map[string]any{"content_type": "text", "parts": []any{"I can't draw that"}},
		}},
	}}
	code, detail := ClassifyConversationFailure(raw)
	if code != "upstream_text_reply" {
		t.Fatalf("code=%q detail=%q", code, detail)
	}
	if !strings.Contains(detail, "can't") {
		t.Fatalf("detail=%q", detail)
	}
}

// TestClassifyConversationFailureJSONControl 线上实录：{"skipped_mainline":true}
// 控制帧曾误杀正常生图（同 prompt 重试成功）。JSON 文本不得作为终态回复证据。
func TestClassifyConversationFailureJSONControl(t *testing.T) {
	raw := map[string]any{"mapping": map[string]any{
		"u1": map[string]any{"message": map[string]any{
			"id": "u1", "author": map[string]any{"role": "user"}, "create_time": 100.0,
			"content": map[string]any{"content_type": "text", "parts": []any{"a penguin on ice"}},
		}},
		"a1": map[string]any{"message": map[string]any{
			"id": "a1", "author": map[string]any{"role": "assistant"}, "create_time": 101.0,
			"status": "finished_successfully", "end_turn": true,
			"content": map[string]any{"content_type": "text", "text": `{"skipped_mainline":true}`},
		}},
	}}
	if code, detail := ClassifyConversationFailure(raw); code != "" {
		t.Fatalf("JSON control frame must not fail: %q %q", code, detail)
	}
}

func TestClassifyConversationFailureNoFalsePositive(t *testing.T) {	// 成功态：终态空文本 + sediment 指针（无指针也要求： text 为空不触发）
	raw := map[string]any{"mapping": map[string]any{
		"u1": map[string]any{"message": map[string]any{
			"id": "u1", "author": map[string]any{"role": "user"}, "create_time": 100.0,
			"content": map[string]any{"content_type": "text", "parts": []any{"a cat"}},
		}},
		"a1": map[string]any{"message": map[string]any{
			"id": "a1", "author": map[string]any{"role": "assistant"}, "create_time": 101.0,
			"status": "finished_successfully", "end_turn": true,
			"content": map[string]any{"content_type": "text", "parts": []any{""}},
			"metadata": map[string]any{"is_complete": true},
		}},
		"t1": map[string]any{"message": map[string]any{
			"id": "t1", "author": map[string]any{"role": "tool"}, "create_time": 102.0,
			"content": map[string]any{"content_type": "multimodal_text", "parts": []any{
				map[string]any{"asset_pointer": "sediment://file_00000000abc", "content_type": "image_asset_pointer"},
			}},
		}},
	}}
	if code, detail := ClassifyConversationFailure(raw); code != "" {
		t.Fatalf("success-like doc must not fail: %q %q", code, detail)
	}
	// 生成中：code 调用帧（无终态）不触发
	raw2 := map[string]any{"mapping": map[string]any{
		"u1": map[string]any{"message": map[string]any{
			"id": "u1", "author": map[string]any{"role": "user"}, "create_time": 100.0,
			"content": map[string]any{"content_type": "text", "parts": []any{"a cat"}},
		}},
		"a1": map[string]any{"message": map[string]any{
			"id": "a1", "author": map[string]any{"role": "assistant"}, "create_time": 101.0,
			"status": "in_progress",
			"content": map[string]any{"content_type": "code", "text": "{\"prompt\":\"a cat\"}"},
		}},
	}}
	if code, _ := ClassifyConversationFailure(raw2); code != "" {
		t.Fatalf("in-progress must not fail: %q", code)
	}
}

func TestClassifyConversationFailureBlockedAndTool(t *testing.T) {
	blocked := map[string]any{"mapping": map[string]any{
		"u1": map[string]any{"message": map[string]any{
			"id": "u1", "author": map[string]any{"role": "user"}, "create_time": 1.0,
			"content": map[string]any{"content_type": "text", "parts": []any{"x"}},
		}},
		"a1": map[string]any{"message": map[string]any{
			"id": "a1", "author": map[string]any{"role": "assistant"}, "create_time": 2.0,
			"content":  map[string]any{"content_type": "text", "parts": []any{"blocked"}},
			"metadata": map[string]any{"blocked": true},
		}},
	}}
	if code, _ := ClassifyConversationFailure(blocked); code != "content_policy_violation" {
		t.Fatalf("blocked code=%q", code)
	}
	toolErr := map[string]any{"mapping": map[string]any{
		"t1": map[string]any{"message": map[string]any{
			"id": "t1", "author": map[string]any{"role": "tool"}, "create_time": 3.0,
			"content": map[string]any{"content_type": "system_error", "parts": []any{"boom"}},
		}},
	}}
	if code, _ := ClassifyConversationFailure(toolErr); code != "image_tool_error" {
		t.Fatalf("tool code=%q", code)
	}
}

// failUpstream 模拟终态失败会话：轮询应秒级抛明确错误，而非等超时。
type failUpstream struct {
	polled int
}

func (f *failUpstream) FetchConversation(ctx context.Context, id string) (*ConversationDoc, time.Duration, error) {
	f.polled++
	return &ConversationDoc{FailureCode: "upstream_text_reply", FailureDetail: "I can't draw that"}, 0, nil
}

func TestPollFileIDsFastFail(t *testing.T) {
	up := &failUpstream{}
	p := fastPolicy()
	p.Timeout = 60 * time.Second
	start := time.Now()
	_, _, err := PollFileIDs(context.Background(), up, "c", p, nil, nil, nil)
	if err == nil || !strings.Contains(err.Error(), "upstream_text_reply") {
		t.Fatalf("err=%v want upstream_text_reply", err)
	}
	if up.polled != 2 {
		t.Fatalf("polled=%d want 2 (confirm same signal twice, still seconds)", up.polled)
	}
	if elapsed := time.Since(start); elapsed > 15*time.Second {
		t.Fatalf("elapsed=%v want fast fail", elapsed)
	}
}

// flakyUpstream 首轮失败信号、次轮干净：过渡态不得误杀，应继续轮询。
type flakyUpstream struct {
	polled int
}

func (f *flakyUpstream) FetchConversation(ctx context.Context, id string) (*ConversationDoc, time.Duration, error) {
	f.polled++
	if f.polled == 1 {
		return &ConversationDoc{FailureCode: "upstream_text_reply", FailureDetail: "x"}, 0, nil
	}
	return &ConversationDoc{FileIDs: []string{"f1"}}, 0, nil
}

func TestPollFileIDsFlakyNoFalseKill(t *testing.T) {
	up := &flakyUpstream{}
	p := fastPolicy()
	p.Timeout = 10 * time.Second
	ids, _, err := PollFileIDs(context.Background(), up, "c", p, nil, nil, nil)
	if err != nil {
		t.Fatalf("transient signal must not kill poll: %v", err)
	}
	if len(ids) != 1 {
		t.Fatalf("ids=%v", ids)
	}
}
