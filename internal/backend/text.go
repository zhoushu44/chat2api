package backend

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"net/http"
	"time"

	"chatgpt2api/internal/sse"
	fhttp "github.com/bogdanfinn/fhttp"
	"github.com/google/uuid"
)

// 文本对话链路（P2.1/P2.4）：对等 openai_backend_api.stream_conversation 文本分支。
// 流程：bootstrap → requirements → POST /backend-api/conversation（action=next）→ SSE。

// ChatTarget 对等 _chat_target：有 token 走 auth 路径，否则 anon。
func (b *Backend) ChatTarget() (path, timezone string) {
	if b.AccessToken != "" {
		return "/backend-api/conversation", "Asia/Shanghai"
	}
	return "/backend-anon/conversation", "America/Los_Angeles"
}

// ConversationHeaders 对等 _conversation_headers：sentinel 全套 token。
func (b *Backend) ConversationHeaders(path string, req *ChatRequirements) http.Header {
	extra := map[string]string{
		"Accept":       "text/event-stream",
		"Content-Type": "application/json",
		"OpenAI-Sentinel-Chat-Requirements-Token": req.Token,
	}
	if req.ProofToken != "" {
		extra["OpenAI-Sentinel-Proof-Token"] = req.ProofToken
	}
	if req.TurnstileToken != "" {
		extra["OpenAI-Sentinel-Turnstile-Token"] = req.TurnstileToken
	}
	if req.SoToken != "" {
		extra["OpenAI-Sentinel-SO-Token"] = req.SoToken
	}
	return b.RequestHeaders(path, extra)
}

// APIMessagesToConversationMessages 对等 _api_messages_to_conversation_messages：
// 标准 chat messages → web conversation messages（id/author/content.parts）。
func APIMessagesToConversationMessages(messages []map[string]any) ([]map[string]any, error) {
	out := make([]map[string]any, 0, len(messages))
	for _, item := range messages {
		role, _ := item["role"].(string)
		if role == "" {
			role = "user"
		}
		content := item["content"]
		if s, ok := content.(string); ok {
			out = append(out, map[string]any{
				"id":      uuid.NewString(),
				"author":  map[string]any{"role": role},
				"content": map[string]any{"content_type": "text", "parts": []string{s}},
			})
			continue
		}
		if arr, ok := content.([]any); ok {
			var textParts []string
			var parts []any
			for _, p := range arr {
				pm, ok := p.(map[string]any)
				if !ok {
					continue
				}
				switch strVal(pm["type"]) {
				case "text":
					t := strVal(pm["text"])
					textParts = append(textParts, t)
					parts = append(parts, map[string]any{"content_type": "text", "parts": []string{t}})
				case "image_url":
					// image_url → 引用（文本链路仅透传文本；图片走生图链路）
					if u := imageURLFromPart(pm); u != "" {
						textParts = append(textParts, "[image: "+u+"]")
					}
				}
			}
			out = append(out, map[string]any{
				"id":      uuid.NewString(),
				"author":  map[string]any{"role": role},
				"content": map[string]any{"content_type": "text", "parts": textParts},
				"_parts":  parts,
			})
			continue
		}
		return nil, fmt.Errorf("only string or list message content is supported")
	}
	return out, nil
}

func strVal(v any) string {
	s, _ := v.(string)
	return s
}

// imageURLFromPart 从 image_url part 提取 URL（{"image_url": {"url": ...}} 或 {"image_url": "..."}）。
func imageURLFromPart(pm map[string]any) string {
	switch v := pm["image_url"].(type) {
	case string:
		return v
	case map[string]any:
		s, _ := v["url"].(string)
		return s
	}
	if s, ok := pm["url"].(string); ok {
		return s
	}
	return ""
}

// ConversationPayload 对等 _conversation_payload：web 对话请求体。
func ConversationPayload(convMessages []map[string]any, model, timezone, thinkingEffort string) map[string]any {
	// strip 内部 _parts
	msgs := make([]map[string]any, 0, len(convMessages))
	for _, m := range convMessages {
		cp := map[string]any{}
		for k, v := range m {
			if k == "_parts" {
				continue
			}
			cp[k] = v
		}
		msgs = append(msgs, cp)
	}
	payload := map[string]any{
		"action":                   "next",
		"messages":                 msgs,
		"model":                    model,
		"parent_message_id":        uuid.NewString(),
		"conversation_mode":        map[string]any{"kind": "primary_assistant"},
		"conversation_origin":      nil,
		"force_paragen":            false,
		"force_paragen_model_slug": "",
		"force_rate_limit":         false,
		"force_use_sse":            true,
		"history_and_training_disabled": true,
		"reset_rate_limits":        false,
		"suggestions":              []any{},
		"supported_encodings":      []any{},
		"system_hints":             []any{},
		"timezone":                 timezone,
		"timezone_offset_min":      -480,
		"variant_purpose":          "comparison_implicit",
		"websocket_request_id":     uuid.NewString(),
		"client_contextual_info": map[string]any{
			"is_dark_mode":     false,
			"time_since_loaded": 120,
			"page_height":      900,
			"page_width":       1400,
			"pixel_ratio":      2,
			"screen_height":    1440,
			"screen_width":     2560,
		},
	}
	if thinkingEffort != "" {
		payload["thinking_effort"] = thinkingEffort
	}
	return payload
}

// StartTextConversation 启动文本对话 SSE（对等 stream_conversation 文本分支）。
// bootstrap + requirements 由调用方完成（或传 nil reqs 自动获取）；返回原始 SSE Body。
func (b *Backend) StartTextConversation(ctx context.Context, messages []map[string]any, model, thinkingEffort string, reqs *ChatRequirements) (io.ReadCloser, error) {
	if reqs == nil {
		if err := b.Bootstrap(ctx); err != nil {
			return nil, fmt.Errorf("bootstrap: %w", err)
		}
		var err error
		reqs, err = b.GetChatRequirements(ctx)
		if err != nil {
			return nil, fmt.Errorf("get requirements: %w", err)
		}
	}
	convMsgs, err := APIMessagesToConversationMessages(messages)
	if err != nil {
		return nil, err
	}
	path, timezone := b.ChatTarget()
	payload := ConversationPayload(convMsgs, model, timezone, thinkingEffort)
	headers := b.ConversationHeaders(path, reqs)
	streamTimeout := 300 * time.Second
	if deadline, ok := ctx.Deadline(); ok {
		if d := time.Until(deadline); d > 0 && d < 300*time.Second {
			streamTimeout = d
		}
	}
	reqCtx, cancel := context.WithTimeout(ctx, streamTimeout)
	freq, err := fhttp.NewRequestWithContext(reqCtx, fhttp.MethodPost, b.BaseURL+path, bytes.NewReader(mustJSON(payload)))
	if err != nil {
		cancel()
		return nil, fmt.Errorf("build %s request: %w", path, err)
	}
	freq.Header = fhttp.Header(headers)
	resp, err := b.http.Do(freq)
	if err != nil {
		cancel()
		return nil, fmt.Errorf("post %s failed: %w", path, err)
	}
	if err := ensureOK(resp.StatusCode, resp.Header.Get("Retry-After"), nil, path, "account"); err != nil {
		bts, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		_ = resp.Body.Close()
		cancel()
		return nil, ensureOK(resp.StatusCode, resp.Header.Get("Retry-After"), bts, path, "account")
	}
	resp.Body = &cancelReadCloser{ReadCloser: resp.Body, cancel: cancel}
	return resp.Body, nil
}

// StreamTextPayloads 文本 SSE 原始 payload 迭代（对等 iter_sse_payloads）。
// 每个 payload 调用 onPayload；返回首个捕获的 conversation_id。
func StreamTextPayloads(ctx context.Context, body io.Reader, streamTimeout time.Duration, onPayload func(payload string)) (string, error) {
	if streamTimeout <= 0 {
		streamTimeout = 300 * time.Second
	}
	var conversationID string
	marker, err := sse.New(body, streamTimeout, func(payload string) (bool, sse.TerminalMarker) {
		if conversationID == "" {
			if m := conversationIDRe.FindStringSubmatch(payload); len(m) == 2 {
				conversationID = m[1]
			}
		}
		if onPayload != nil {
			onPayload(payload)
		}
		return false, sse.TerminalMarker{}
	}).Run(ctx)
	if err != nil {
		return conversationID, err
	}
	if conversationID == "" && marker.ConversationID != "" {
		conversationID = marker.ConversationID
	}
	return conversationID, nil
}
