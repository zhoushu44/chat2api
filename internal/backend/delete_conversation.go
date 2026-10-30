package backend

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"chatgpt2api/internal/backend/failure"

	fhttp "github.com/bogdanfinn/fhttp"
)

// DeleteConversation 删除上游会话记录（生图后清理痕迹）。
// 对齐 basketikun/chatgpt2api 的 image_remove_conversation_after_result：
// 生图成功后删除会话，避免会话累积被风控关联。
// 失败不阻断主流程（best-effort）。
func (b *Backend) DeleteConversation(ctx context.Context, conversationID string) error {
	if conversationID == "" {
		return nil
	}
	path := fmt.Sprintf("/backend-api/conversations/%s", conversationID)
	headers := b.RequestHeaders(path, map[string]string{
		"Accept":       "application/json",
		"Content-Type": "application/json",
	})
	body, _ := json.Marshal(map[string]any{"is_visible": false})
	reqCtx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	resp, respBody, err := b.doJSONRequest(reqCtx, fhttp.MethodPatch, b.BaseURL+path, headers, body)
	if err != nil {
		return fmt.Errorf("delete conversation: %w", err)
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		f := failure.Classify(fmt.Errorf("upstream returned %d", resp.StatusCode), resp.StatusCode, string(respBody))
		return fmt.Errorf("delete conversation: %s (%d)", f.Code, resp.StatusCode)
	}
	return nil
}
