package backend

import (
	"context"
	"errors"
	"fmt"
	"io"
	"time"

	"chatgpt2api/internal/sse"
)

// ConversationStarter SSE 会话发起抽象（真实实现 = tls-client POST 官网 conversation 接口）。
type ConversationStarter interface {
	StartConversation(ctx context.Context, prompt string) (io.ReadCloser, string, error)
}

// RunImagePipeline 生图管线编排：SSE 阶段（终止标记驱动）→ 轮询阶段（事件驱动）。
//
// 对等 Python conversation.py 的 stream_image_outputs 主干，
// 差异见 PollFileIDs 注释（10s 预算的三个来源）。
// M1.4 真实接入时：starter/upstream 换成 tls-client 实现，下载阶段补齐。
func RunImagePipeline(
	ctx context.Context,
	starter ConversationStarter,
	up Upstream,
	prompt string,
	policy PollPolicy,
	timing *StageTiming,
) (*ImageResult, error) {
	if timing == nil {
		timing = &StageTiming{}
	}
	pipeStart := time.Now()

	// ---- 阶段 1：SSE 上行流 ----
	t := time.Now()
	rc, conversationID, err := starter.StartConversation(ctx, prompt)
	if err != nil {
		return nil, fmt.Errorf("start conversation: %w", err)
	}
	streamTimeout := policy.StreamTimeout
	if streamTimeout <= 0 {
		streamTimeout = 120 * time.Second
	}
	parser := NewStreamParser()
	marker, sseErr := sse.New(rc, streamTimeout, parser.OnPayload).Run(ctx)
	_ = rc.Close()
	// 真实链路：starter 可能未同步返回 conversationID（需从 SSE payload 正则提取），用 marker 回填
	if conversationID == "" && marker.ConversationID != "" {
		conversationID = marker.ConversationID
	}
	// 流读取错误但已有流内 ID 时，Python 版有恢复逻辑（_recover_after_image_stream_timeout）；
	// M1.4 真实实现补齐，mock 阶段直接透传错误。
	if sseErr != nil && !errors.Is(sseErr, context.Canceled) {
		// 若已有 fileIDs 或 conversationID，视为可恢复（轮询可继续）；否则透传错误
		if len(parser.FileIDs()) == 0 && conversationID == "" {
			return nil, fmt.Errorf("sse stream: %w", sseErr)
		}
		err = sseErr
	}
	timing.SSEStreamMs = msSince(t)

	// ---- 阶段 2：事件驱动轮询（流内 asset pointer 作为初始 ID）----
	fileIDs, sedimentIDs, err := PollFileIDs(ctx, up, conversationID, policy, parser.FileIDs(), nil, timing)
	if err != nil {
		return nil, err
	}

	// ---- 阶段 3：下载（M1.4：并发下载 ≤4，流式落盘）----
	// mock 阶段跳过；真实实现在此填充 result.Bytes/URLs。

	timing.TotalMs = msSince(pipeStart)
	return &ImageResult{FileIDs: fileIDs, SedimentIDs: sedimentIDs, Stage: *timing}, nil
}
