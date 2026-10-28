package backend

import (
	"context"
	"strings"
	"testing"
	"time"
)

func contains(s, sub string) bool { return strings.Contains(s, sub) }

// ---- 参考图排除：账号失效时会话里只剩用户上传的 attachment，不得当作生成结果 ----

// referenceOnlyUpstream 模拟「上游没出图，会话里只有参考图 attachment」。
type referenceOnlyUpstream struct {
	refID string
}

func (u *referenceOnlyUpstream) FetchConversation(ctx context.Context, id string) (*ConversationDoc, time.Duration, error) {
	return &ConversationDoc{
		FileIDs:     []string{u.refID},
		SedimentIDs: []string{u.refID},
	}, 0, nil
}

func TestPollFileIDsExcludesReferenceIDs(t *testing.T) {
	up := &referenceOnlyUpstream{refID: "file_ref_abc"}
	p := fastPolicy()
	// 传入与上游返回相同的参考图 ID，必须被排除；
	// 且「只有参考图、无新图」应快速失败，而不是空轮询到超时
	_, _, err := PollFileIDs(context.Background(), up, "c", p,
		nil, nil,
		[]string{"file_ref_abc"}, []string{"file_ref_abc"},
		&StageTiming{})
	if err == nil {
		t.Fatal("只有参考图、无新图时应返回错误")
	}
	if got := err.Error(); !contains(got, "no_image_generated") {
		t.Fatalf("err=%v want no_image_generated（参考图被排除后不得当结果返回）", err)
	}
}

// mixedUpstream 会话里同时含参考图和真实生成图。
type mixedUpstream struct {
	refID string
	newID string
}

func (u *mixedUpstream) FetchConversation(ctx context.Context, id string) (*ConversationDoc, time.Duration, error) {
	return &ConversationDoc{
		FileIDs:     []string{u.refID, u.newID},
		SedimentIDs: []string{u.refID},
	}, 0, nil
}

func TestPollFileIDsKeepsGeneratedImageExcludesReference(t *testing.T) {
	up := &mixedUpstream{refID: "file_ref_abc", newID: "file_new_xyz"}
	p := fastPolicy()
	files, sediments, err := PollFileIDs(context.Background(), up, "c", p,
		nil, nil,
		[]string{"file_ref_abc"}, []string{"file_ref_abc"},
		&StageTiming{})
	if err != nil {
		t.Fatalf("err: %v", err)
	}
	if len(files) != 1 || files[0] != "file_new_xyz" {
		t.Fatalf("应只保留真实生成图，实际=%v", files)
	}
	if len(sediments) != 0 {
		t.Fatalf("参考图 sediment 应被排除，实际=%v", sediments)
	}
}

func TestFilterExcludedAndMergeExcluded(t *testing.T) {
	exclude := toSet([]string{"a", "b"})
	got := filterExcluded([]string{"a", "b", "c"}, exclude)
	if len(got) != 1 || got[0] != "c" {
		t.Fatalf("filterExcluded=%v", got)
	}
	// 空 exclude：原样返回
	if filterExcluded([]string{"a"}, nil) == nil {
		t.Fatal("空 exclude 不应改变输入")
	}
	// mergeExcluded：新增中被排除的不得进入
	merged := mergeExcluded([]string{"a", "d"}, []string{"c"}, exclude)
	if len(merged) != 2 || merged[0] != "c" || merged[1] != "d" {
		t.Fatalf("mergeExcluded=%v", merged)
	}
}

// ---- 文本速败：无 end_turn / 无终态 status 的「Hi! 欢迎回来！」也应判失败 ----

func TestClassifyConversationFailureTextReplyWithoutTerminalMarkers(t *testing.T) {
	// 上游只回文本，没有 end_turn、没有终态 status——原逻辑会漏判
	raw := map[string]any{"mapping": map[string]any{
		"u1": map[string]any{"message": map[string]any{
			"id": "u1", "author": map[string]any{"role": "user"},
			"create_time": 100.0,
			"content":     map[string]any{"content_type": "text", "parts": []any{"draw a cat"}},
		}},
		"a1": map[string]any{"message": map[string]any{
			"id": "a1", "author": map[string]any{"role": "assistant"},
			"create_time": 101.0,
			// 故意不带 end_turn / status
			"content": map[string]any{"content_type": "text", "parts": []any{"Hi! 👋 欢迎回来！"}},
		}},
	}}
	code, detail := ClassifyConversationFailure(raw)
	if code != "upstream_text_reply" {
		t.Fatalf("code=%q want upstream_text_reply（有文本无图片指针即失败）detail=%q", code, detail)
	}
}
