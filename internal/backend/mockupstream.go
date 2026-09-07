package backend

import (
	"context"
	"fmt"
	"io"
	"strconv"
	"sync"
	"time"
)

// MockUpstream 模拟 ChatGPT 官网行为（M1 调度验证，不依赖真实账号）。
//
// 模拟的官网特征（均来自 Python 版源码注释与实测行为）：
//   - SSE 流在终止标记后连接保持打开（openai_backend_api.py:416 注释）
//   - SSE 关闭后 ~200ms 内轮询会话文档会撞瞬时 429（:2635 注释）
//   - 会话文档在生成完成后才出现 file_ids（存在提交延迟）
type MockUpstream struct {
	// StreamDuration 会话开始到终止标记出现的时长（模拟上游生成耗时）。
	StreamDuration time.Duration
	// ReadyAfter 会话开始到会话文档出现 file_ids 的时长（含提交延迟）。
	ReadyAfter time.Duration
	// EmitAssetPointer SSE 流内是否携带 asset pointer（流内快路径开关）。
	EmitAssetPointer bool
	// RateLimitWindow 流结束后该窗口内轮询返回 429 + RetryAfter（0 = 不模拟）。
	RateLimitWindow time.Duration
	// RetryAfter 429 响应的 Retry-After。
	RetryAfter time.Duration
	// FileID 模拟生成的图片 file id。
	FileID string

	mu            sync.Mutex
	convStart     time.Time
	streamEndedAt time.Time
}

var _ ConversationStarter = (*MockUpstream)(nil)
var _ Upstream = (*MockUpstream)(nil)

// StartConversation 发起模拟 SSE 会话。
func (m *MockUpstream) StartConversation(ctx context.Context, prompt string) (io.ReadCloser, string, error) {
	m.mu.Lock()
	m.convStart = time.Now()
	convID := "mock-conv-" + strconv.FormatInt(m.convStart.UnixNano(), 36)
	m.mu.Unlock()

	pr, pw := io.Pipe()
	go func() {
		// 帧时刻游标：保证终止标记始终在 StreamDuration 时刻发出
		cursor := time.Duration(0)
		writeFrame := func(payload string, at time.Duration) bool {
			delay := at - cursor
			if delay < 0 {
				delay = 0
			}
			cursor = at
			select {
			case <-time.After(delay):
			case <-ctx.Done():
				return false
			}
			_, err := pw.Write([]byte("data: " + payload + "\n\n"))
			return err == nil
		}

		// 帧序列：delta → （可选）tool args 携带 asset pointer → 终止标记（StreamDuration 时刻）
		if !writeFrame(`{"v":{"type":"delta","delta":"generating"}}`, 200*time.Millisecond) {
			pw.Close()
			return
		}
		if m.EmitAssetPointer {
			args := fmt.Sprintf(`{"v":{"type":"tool_args","arguments":"{\"action\":\"generate\",\"image_asset_pointer\":{\"asset_pointer\":\"file-service://%s\"}}"}}`, m.FileID)
			if !writeFrame(args, m.StreamDuration-500*time.Millisecond) {
				pw.Close()
				return
			}
		}
		if !writeFrame(`{"v":{"type":"message","message":{"status":"finished_successfully","metadata":{"is_complete":true}}}}`, m.StreamDuration) {
			pw.Close()
			return
		}
		m.mu.Lock()
		m.streamEndedAt = time.Now()
		m.mu.Unlock()
		// 官网行为：标记后连接保持打开——scanner 已在标记处返回，这里挂住模拟
		select {
		case <-ctx.Done():
		case <-time.After(30 * time.Second):
		}
		pw.Close()
	}()
	return pr, convID, nil
}

// FetchConversation 拉取模拟会话文档。
func (m *MockUpstream) FetchConversation(ctx context.Context, conversationID string) (*ConversationDoc, time.Duration, error) {
	m.mu.Lock()
	convStart, ended := m.convStart, m.streamEndedAt
	m.mu.Unlock()

	// 模拟官网瞬时 429：流结束后的短窗口内
	if m.RateLimitWindow > 0 && !ended.IsZero() && time.Since(ended) < m.RateLimitWindow {
		return nil, m.RetryAfter, nil
	}
	if !convStart.IsZero() && time.Since(convStart) >= m.ReadyAfter {
		return &ConversationDoc{FileIDs: []string{m.FileID}}, 0, nil
	}
	return &ConversationDoc{}, 0, nil
}
