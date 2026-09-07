package backend

import (
	"context"
	"errors"
	"testing"
	"time"
)

// fakeUpstream 快速轮询测试用的可编程上游。
type fakeUpstream struct {
	readyAt        time.Time
	retryAfterOnce time.Duration // >0：所有就绪前的拉取都返回 429（窗口内）
	retryWindow    time.Time     // 429 窗口截止时刻（zero = 不限）
	polled         int
}

func (f *fakeUpstream) FetchConversation(ctx context.Context, id string) (*ConversationDoc, time.Duration, error) {
	f.polled++
	if f.retryAfterOnce > 0 && time.Now().Before(f.retryWindow) {
		return nil, f.retryAfterOnce, nil
	}
	if !time.Now().Before(f.readyAt) {
		return &ConversationDoc{FileIDs: []string{"f1"}}, 0, nil
	}
	return &ConversationDoc{}, 0, nil
}

func fastPolicy() PollPolicy {
	return PollPolicy{
		InitialWait: 5 * time.Millisecond,
		Interval:    5 * time.Millisecond,
		MaxInterval: 15 * time.Millisecond,
		Timeout:     2 * time.Second,
		Settle:      5 * time.Millisecond,
	}
}

func TestPollFileIDsSettleConfirm(t *testing.T) {
	up := &fakeUpstream{readyAt: time.Now().Add(30 * time.Millisecond)}
	timing := &StageTiming{}
	ids, _, err := PollFileIDs(context.Background(), up, "c", fastPolicy(), nil, nil, timing)
	if err != nil {
		t.Fatalf("err: %v", err)
	}
	if len(ids) != 1 || ids[0] != "f1" {
		t.Fatalf("ids: %v", ids)
	}
	// settle 语义：首见 + 确认，至少 2 次拉取
	if timing.PollCount < 2 {
		t.Fatalf("PollCount=%d, want >=2（settle 确认缺失）", timing.PollCount)
	}
}

func TestPollFileIDsStreamIDsFastPath(t *testing.T) {
	// 流内已解析出 asset pointer：首次拉取即确认
	up := &fakeUpstream{readyAt: time.Now()}
	timing := &StageTiming{}
	ids, _, err := PollFileIDs(context.Background(), up, "c", fastPolicy(), []string{"f1"}, nil, timing)
	if err != nil {
		t.Fatalf("err: %v", err)
	}
	if len(ids) != 1 || ids[0] != "f1" {
		t.Fatalf("ids: %v", ids)
	}
	if timing.PollCount != 1 {
		t.Fatalf("PollCount=%d, want 1（快路径应一次确认）", timing.PollCount)
	}
}

func TestPollFileIDsRateLimited(t *testing.T) {
	// 首询 429，Retry-After 20ms 必须被遵守
	up := &fakeUpstream{
		readyAt:        time.Now().Add(10 * time.Millisecond),
		retryAfterOnce: 20 * time.Millisecond,
		retryWindow:    time.Now().Add(50 * time.Millisecond),
	}
	timing := &StageTiming{}
	start := time.Now()
	_, _, err := PollFileIDs(context.Background(), up, "c", fastPolicy(), nil, nil, timing)
	if err != nil {
		t.Fatalf("err: %v", err)
	}
	// 首询 5ms 后 429 → 至少再等 20ms → 25ms 后第二次拉取
	if elapsed := time.Since(start); elapsed < 25*time.Millisecond {
		t.Fatalf("elapsed=%v, Retry-After 未被遵守", elapsed)
	}
}

func TestPollFileIDsTimeout(t *testing.T) {
	up := &fakeUpstream{readyAt: time.Now().Add(time.Hour)} // 永不就绪
	p := fastPolicy()
	p.Timeout = 50 * time.Millisecond
	_, _, err := PollFileIDs(context.Background(), up, "c", p, nil, nil, nil)
	if !errors.Is(err, ErrPollTimeout) {
		t.Fatalf("err: %v, want ErrPollTimeout", err)
	}
}

func TestPollFileIDsAdaptiveBackoff(t *testing.T) {
	// 就绪时间足够晚，触发多次空轮询：等待序列 5ms→10ms→15ms（封顶）
	up := &fakeUpstream{readyAt: time.Now().Add(80 * time.Millisecond)}
	timing := &StageTiming{}
	_, _, err := PollFileIDs(context.Background(), up, "c", fastPolicy(), nil, nil, timing)
	if err != nil {
		t.Fatalf("err: %v", err)
	}
	// 初始等待 5ms 之外，空轮询等待累计应 ≥ 5+10 = 15ms（自适应递增生效）
	if timing.PollWaitMs < 15 {
		t.Fatalf("PollWaitMs=%d, want >=15（自适应递增未生效）", timing.PollWaitMs)
	}
}

func TestParseStreamPayload(t *testing.T) {
	// 终止标记：finished_successfully + is_complete 同时为 true
	term := `{"v":{"message":{"status":"finished_successfully","metadata":{"is_complete":true}}}}`
	if ok, _ := ParseStreamPayload([]byte(term)); !ok {
		t.Fatal("终止标记未被识别")
	}
	// 只有 finished_successfully：不终止（官网部分帧只有半边标记）
	half := `{"v":{"message":{"status":"finished_successively","metadata":{"is_complete":false}}}}`
	if ok, _ := ParseStreamPayload([]byte(half)); ok {
		t.Fatal("半边标记误判为终止")
	}
	// asset pointer 提取（tool args 为转义 JSON）+ 跨帧去重
	toolArgs := `{"v":{"type":"tool_args","arguments":"{\"image_asset_pointer\":{\"asset_pointer\":\"file-service://file-abc\"}}"}}`
	_, ids1 := ParseStreamPayload([]byte(toolArgs))
	_, ids2 := ParseStreamPayload([]byte(toolArgs))
	ids := mergeUnique(ids1, ids2)
	if len(ids) != 1 || ids[0] != "file-abc" {
		t.Fatalf("ids: %v", ids)
	}
	// 非 JSON 帧安全忽略
	if ok, ids := ParseStreamPayload([]byte("[DONE]")); ok || len(ids) != 0 {
		t.Fatalf("[DONE] 误解析: ok=%v ids=%v", ok, ids)
	}
}

func TestStreamParserAccumulate(t *testing.T) {
	p := NewStreamParser()
	p.OnPayload(`{"v":{"type":"tool_args","arguments":"{\"asset_pointer\":\"file-service://file-1\"}"}}`)
	terminal, marker := p.OnPayload(`{"v":{"message":{"status":"finished_successfully","metadata":{"is_complete":true}}}}`)
	if !terminal {
		t.Fatal("终止标记未触发")
	}
	if len(marker.FileIDs) != 1 || marker.FileIDs[0] != "file-1" {
		t.Fatalf("marker.FileIDs: %v", marker.FileIDs)
	}
}
