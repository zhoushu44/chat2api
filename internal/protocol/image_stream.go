package protocol

import (
	"context"
	"encoding/base64"
	"fmt"
	"time"

	"chatgpt2api/internal/account"
	"chatgpt2api/internal/backend"
	"chatgpt2api/internal/backend/failure"
	"chatgpt2api/internal/logsvc"
	"chatgpt2api/internal/monitor/metrics"
	"chatgpt2api/internal/utils"
)

// 生图输出流（P2.4）：对等 conversation.py ImageOutput 三态（progress/result/message）+ to_chunk。
// orchestrator.GenerateStream 在各阶段推送 progress，结束推送 result；失败推送 message(kind=message 带错误)。

// ImageOutputKind 输出 kinds。
type ImageOutputKind string

const (
	ImageOutputProgress ImageOutputKind = "progress"
	ImageOutputResult   ImageOutputKind = "result"
	ImageOutputMessage  ImageOutputKind = "message"
)

// ImageOutput 单次生图输出（对等 ImageOutput dataclass）。
type ImageOutput struct {
	Kind          ImageOutputKind
	Model         string
	Index         int
	Total         int
	Created       int64
	Text          string // progress 文本 / message 文本
	Data          []map[string]string
	ImageURLs     []string
	ImageAttempts []map[string]any
	AccountEmail  string
	Conversation  string
}

// ToChunk 输出块（对等 to_chunk）。
func (o ImageOutput) ToChunk() map[string]any {
	chunk := map[string]any{
		"object":              "image.generation.chunk",
		"created":             o.Created,
		"model":               o.Model,
		"index":               o.Index,
		"total":               o.Total,
		"progress_text":       o.Text,
		"upstream_event_type": "",
		"data":                []any{},
	}
	if o.AccountEmail != "" {
		chunk["_account_email"] = o.AccountEmail
	}
	if o.Conversation != "" {
		chunk["_conversation_id"] = o.Conversation
	}
	if len(o.ImageURLs) > 0 {
		chunk["_image_urls"] = append([]string(nil), o.ImageURLs...)
	}
	if len(o.ImageAttempts) > 0 {
		chunk["_image_attempts"] = o.ImageAttempts
	}
	switch o.Kind {
	case ImageOutputMessage:
		chunk["object"] = "image.generation.message"
		chunk["message"] = o.Text
		delete(chunk, "progress_text")
		delete(chunk, "upstream_event_type")
	case ImageOutputResult:
		chunk["object"] = "image.generation.result"
		data := make([]any, 0, len(o.Data))
		for _, d := range o.Data {
			m := map[string]any{}
			for k, v := range d {
				m[k] = v
			}
			data = append(data, m)
		}
		chunk["data"] = data
		delete(chunk, "progress_text")
		delete(chunk, "upstream_event_type")
	}
	return chunk
}

// GenerateStream 生图流（P2.4）：账号轮换 + 阶段 progress + 结果/失败。
// onOutput 每个 ImageOutput 调用一次；返回聚合结果（URLs/B64）。
// 对等 stream_image_outputs_with_pool + collect_image_outputs 的 Go 形态。
func (o *Orchestrator) GenerateStream(ctx context.Context, req GenerateRequest, onOutput func(ImageOutput)) (*GenerateResult, error) {
	if req.Model == "" {
		req.Model = "gpt-image-2"
	}
	if req.N == 0 {
		req.N = 1
	}
	emit := func(out ImageOutput) {
		if out.Created == 0 {
			out.Created = time.Now().Unix()
		}
		if out.Model == "" {
			out.Model = req.Model
		}
		if onOutput != nil {
			onOutput(out)
		}
	}
	attempts := o.Config.MaxAttempts
	if attempts == 0 {
		attempts = 3
	}
	var lastErr error
	excluded := make(map[string]bool)
	for attempt := 0; attempt < attempts; attempt++ {
		sel := account.Selector{Excluded: excluded, MaxInflight: o.Config.Concurrency}
		acc := o.Pool.Pick(sel)
		if acc == nil {
			break
		}
		be, err := o.getBackend(acc)
		if err != nil {
			o.Pool.Release(acc)
			lastErr = err
			continue
		}
		_ = o.Pool.EnsureFreshToken(acc)
		if err := utilsCheckContent(req.Prompt); err != nil {
			o.Pool.Release(acc)
			return nil, err
		}
		// 阶段 progress（对等 Python progress_callback 步骤）
		emit(ImageOutput{Kind: ImageOutputProgress, Index: attempt, Total: attempts, Text: "uploading", AccountEmail: acc.Email})
		res, err := o.generateOne(ctx, be, acc, req, emit, attempt, attempts)
		if err == nil {
			o.Pool.Release(acc)
			return res, nil
		}
		lastErr = err
		emit(ImageOutput{Kind: ImageOutputMessage, Index: attempt, Total: attempts, Text: err.Error(), AccountEmail: acc.Email})
		f := classifyFailure(err)
		o.Pool.Release(acc)
		if isAuthFailure(f) {
			o.deactivateAccount(acc)
			excluded[acc.Token] = true
			continue
		}
		if !f.SwitchAccount() {
			break
		}
		o.Pool.Cooldown(acc, time.Now().Add(30*time.Second))
		excluded[acc.Token] = true
	}
	if lastErr != nil {
		return nil, wrapAllFailed(lastErr)
	}
	return nil, errNoAccount()
}

// generateOne 单账号一次生图（含 progress 推送与结果组装）。
func (o *Orchestrator) generateOne(ctx context.Context, be *backend.Backend, acc *account.Account, req GenerateRequest, emit func(ImageOutput), attempt, attempts int) (*GenerateResult, error) {
	emit(ImageOutput{Kind: ImageOutputProgress, Index: attempt, Total: attempts, Text: "bootstrapping", AccountEmail: acc.Email})
	policy := defaultPollPolicy()
	res, err := be.GenerateImage(ctx, req.Prompt, req.Model, req.Images, policy)
	if err != nil {
		return nil, err
	}
	emit(ImageOutput{Kind: ImageOutputProgress, Index: attempt, Total: attempts, Text: "resolving", AccountEmail: acc.Email, Conversation: res.ConversationID})
	urls, rerr := be.ResolveImageURLs(ctx, res.ConversationID, res.FileIDs, res.SedimentIDs)
	if rerr != nil {
		return nil, wrapResolve(rerr)
	}
	var b64Data [][]byte
	if len(urls) > 0 {
		emit(ImageOutput{Kind: ImageOutputProgress, Index: attempt, Total: attempts, Text: "downloading", AccountEmail: acc.Email, Conversation: res.ConversationID})
		if datas, derr := be.DownloadImages(ctx, urls); derr == nil {
			for _, d := range datas {
				b64Data = append(b64Data, encodeB64Bytes(d))
			}
		}
	}
	data := make([]map[string]string, 0, len(b64Data)+len(urls))
	for _, b := range b64Data {
		data = append(data, map[string]string{"b64_json": string(b), "revised_prompt": req.Prompt})
	}
	for _, u := range urls {
		if len(data) == 0 {
			data = append(data, map[string]string{"url": u, "revised_prompt": req.Prompt})
		}
	}
	out := ImageOutput{Kind: ImageOutputResult, Index: attempt, Total: attempts, Data: data, ImageURLs: urls, AccountEmail: acc.Email, Conversation: res.ConversationID}
	emit(out)
	o.recordGenerateMetrics(req, res, nil)
	if o.Logger != nil {
		o.Logger.Add(&logsvc.LoggedCall{
			ID:        utils.NewUUID(),
			Prompt:    req.Prompt,
			Model:     req.Model,
			Status:    "success",
			CreatedAt: time.Now(),
			Attempts:  []logsvc.Attempt{{AccountID: acc.Email, Code: "ok"}},
		})
	}
	return &GenerateResult{URLs: urls, B64: b64Data, Timing: res.Stage}, nil
}

func classifyFailure(err error) failure.ImageFailure {
	msg := ""
	if err != nil {
		msg = err.Error()
	}
	return failure.Classify(err, 0, msg)
}

func wrapAllFailed(err error) error {
	return fmt.Errorf("all accounts failed: %w", err)
}

func errNoAccount() error {
	return fmt.Errorf("no available account")
}

func wrapResolve(err error) error {
	return fmt.Errorf("resolve image urls: %w", err)
}

func encodeB64Bytes(d []byte) []byte {
	return []byte(base64.StdEncoding.EncodeToString(d))
}

func defaultPollPolicy() backend.PollPolicy {
	return backend.PollPolicy{
		InitialWait: 300 * time.Millisecond,
		Interval:    time.Second,
		MaxInterval: 5 * time.Second,
		Timeout:     60 * time.Second,
		Settle:      time.Second,
		StreamTimeout: 80 * time.Second,
	}
}

// recordGenerateMetrics 生图指标（endpoint=/v1/images/generations）。
func (o *Orchestrator) recordGenerateMetrics(req GenerateRequest, res *backend.ImageResult, err error) {
	if o.Metrics == nil {
		return
	}
	o.Metrics.Record(metrics.CallEvent{
		Status:    metricsStatusOf(err),
		Endpoint:  "/v1/images/generations",
		Model:     req.Model,
		ErrorCode: metricsCodeOf(err),
		At:        time.Now(),
	})
}
