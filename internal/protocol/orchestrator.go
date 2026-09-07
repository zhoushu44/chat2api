package protocol

import (
	"context"
	"encoding/base64"
	"fmt"
	"log"
	"strings"
	"sync"
	"time"

	"chatgpt2api/internal/account"
	"chatgpt2api/internal/backend"
	"chatgpt2api/internal/backend/failure"
	"chatgpt2api/internal/filter"
	"chatgpt2api/internal/logsvc"
	"chatgpt2api/internal/monitor/metrics"
	"chatgpt2api/internal/utils"
)

// Orchestrator 生图编排：多账号重试 + 流式输出 + URL resolve
// 对等 services/protocol/conversation.py:1952-2140
type Orchestrator struct {
	Pool     *account.Pool
	Backends map[string]*backend.Backend // token -> backend（mu 保护，OPT-8 并行 slot 并发读写）
	mu       sync.Mutex
	Logger   *logsvc.Service
	Metrics  *metrics.Metrics // 仪表盘指标（P1.7，可为 nil）
	Config   struct {
		MaxAttempts int
		Concurrency int
		Proxy       string // 出站代理（P2.7：config.EffectiveProxy 注入，backend tls-client 透传）
	}
}

// getBackend 取号池账号对应的 backend（懒创建，线程安全）。
func (o *Orchestrator) getBackend(acc *account.Account) (*backend.Backend, error) {
	o.mu.Lock()
	defer o.mu.Unlock()
	be, ok := o.Backends[acc.Token]
	if ok {
		return be, nil
	}
	b, err := backend.NewBackend(acc.Token, acc.FP, o.Config.Proxy)
	if err != nil {
		return nil, err
	}
	if o.Backends == nil {
		o.Backends = make(map[string]*backend.Backend)
	}
	o.Backends[acc.Token] = b
	return b, nil
}

type GenerateRequest struct {
	Prompt string
	Model  string
	Images []string // base64
	N      int
}

// BuildImagePrompt 对等 Python build_image_prompt：size/quality 以中文 hint 拼到 prompt 末尾。
// quality 为空时调用方应先缺省为 "auto"（对等 body.get("quality") or "auto"）。
func BuildImagePrompt(prompt, size, quality string) string {
	var hints strings.Builder
	if s := strings.TrimSpace(size); s != "" {
		hints.WriteString("输出图片尺寸为 " + s + "。")
	}
	if q := strings.TrimSpace(quality); q != "" {
		hints.WriteString("输出图片质量为 " + q + "。")
	}
	if hints.Len() == 0 {
		return prompt
	}
	return strings.TrimSpace(prompt) + "\n\n" + hints.String()
}

// TextRequest 文本对话请求（P2.1）。
type TextRequest struct {
	Messages       []map[string]any
	Model          string
	ThinkingEffort string
}

type GenerateResult struct {
	URLs   []string
	B64    [][]byte
	Timing backend.StageTiming
}

func NewOrchestrator(pool *account.Pool) *Orchestrator {
	return &Orchestrator{Pool: pool, Backends: make(map[string]*backend.Backend)}
}

// Warmup 启动预热：为号池每个账号建好 backend 并刷新 bootstrap（prompt 无关部分），
// 首个真实请求跳过建连 + 首页 GET（~2-4s）。单账号失败只记日志不阻断，返回预热成功数。
func (o *Orchestrator) Warmup(ctx context.Context) int {
	if o == nil || o.Pool == nil {
		return 0
	}
	warmed := 0
	for _, acc := range o.Pool.List() {
		be, err := o.getBackend(acc)
		if err != nil {
			log.Printf("[warmup] backend %s: %v", acc.Email, err)
			continue
		}
		acctCtx, cancel := context.WithTimeout(ctx, 60*time.Second)
		err = be.Bootstrap(acctCtx)
		cancel()
		if err != nil {
			log.Printf("[warmup] bootstrap %s: %v", acc.Email, err)
			continue
		}
		warmed++
	}
	log.Printf("[warmup] done warmed=%d", warmed)
	return warmed
}

func (o *Orchestrator) Generate(ctx context.Context, req GenerateRequest) (*GenerateResult, error) {
	if req.Model == "" {
		req.Model = "gpt-image-2"
	}
	if req.N == 0 {
		req.N = 1
	}
	if req.N > 4 {
		req.N = 4
	}
	policy := backend.PollPolicy{
		InitialWait: 300 * time.Millisecond,
		Interval:    time.Second,
		MaxInterval: 5 * time.Second,
		Timeout:     60 * time.Second,
		Settle:      time.Second,
		StreamTimeout: 80 * time.Second,
	}
	// 内容审查前置（请求级一次即可，不占用账号）
	if err := utilsCheckContent(req.Prompt); err != nil {
		return nil, err
	}
	// 多图：每 slot 独立走一次完整单图链路（对等 Python 并行/串行模式）。
	// 并发度按号池深度封顶：单号退化为串行（零行为变化），多号自动并行。
	// 顺序按 slot 组装（handler 按下标取图），与串行一致。
	limit := len(o.Pool.List())
	if limit < 1 {
		limit = 1
	}
	if limit > req.N {
		limit = req.N
	}
	type slotOut struct {
		res *GenerateResult
		err error
	}
	outs := make([]slotOut, req.N)
	var wg sync.WaitGroup
	sem := make(chan struct{}, limit)
	for slot := 0; slot < req.N; slot++ {
		wg.Add(1)
		go func(s int) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()
			one, err := o.generateSingle(ctx, req, policy)
			outs[s] = slotOut{res: one, err: err}
		}(slot)
	}
	wg.Wait()
	var urls []string
	var b64Data [][]byte
	var timing backend.StageTiming
	firstTiming := true
	var lastErr error
	okSlots := 0
	for _, out := range outs {
		if out.err != nil {
			lastErr = out.err
			continue
		}
		urls = append(urls, out.res.URLs...)
		b64Data = append(b64Data, out.res.B64...)
		if firstTiming {
			timing = out.res.Timing
			firstTiming = false
		} else {
			timing.TotalMs += out.res.Timing.TotalMs
		}
		okSlots++
	}
	if okSlots == 0 {
		if lastErr != nil {
			return nil, lastErr
		}
		return nil, fmt.Errorf("no available account")
	}
	return &GenerateResult{URLs: urls, B64: b64Data, Timing: timing}, nil
}

// generateSingle 单张图片完整链路：多账号重试 + URL resolve + b64 下载。
func (o *Orchestrator) generateSingle(ctx context.Context, req GenerateRequest, policy backend.PollPolicy) (*GenerateResult, error) {
	var lastErr error
	excluded := make(map[string]bool)
	attempts := o.Config.MaxAttempts
	if attempts == 0 {
		attempts = 3
	}
	for attempt := 0; attempt < attempts; attempt++ {
		pickStart := time.Now()
		sel := account.Selector{Excluded: excluded, MaxInflight: o.Config.Concurrency}
		acc := o.Pool.Pick(sel)
		pickMs := time.Since(pickStart).Milliseconds()
		if acc == nil {
			break
		}
		be, err := o.getBackend(acc)
		if err != nil {
			o.Pool.Release(acc)
			lastErr = fmt.Errorf("create backend: %w", err)
			continue
		}
		// 预刷新 token
		_ = o.Pool.EnsureFreshToken(acc)

		genStart := time.Now()
		res, err := be.GenerateImage(ctx, req.Prompt, req.Model, req.Images, policy)
		genMs := float64(time.Since(genStart).Milliseconds())
		// 仪表盘指标（P1.7，对等 safe_record_dashboard_call）
		if o.Metrics != nil {
			o.Metrics.Record(metrics.CallEvent{
				Status:    metricsStatusOf(err),
				Endpoint:  "/v1/images/generations",
				Model:     req.Model,
				ErrorCode: metricsCodeOf(err),
				Duration:  genMs,
				At:        time.Now(),
			})
		}
		// 记录 image_attempts（对等 log_service image_attempts）
		if o.Logger != nil {
			o.Logger.Add(&logsvc.LoggedCall{
				ID:        utils.NewUUID(),
				Prompt:    req.Prompt,
				Model:     req.Model,
				Status:    statusOf(err),
				CreatedAt: time.Now(),
				Attempts:  []logsvc.Attempt{{AccountID: acc.Email, Code: codeOf(err)}},
			})
		}
		if err == nil {
			// 解析 URL（并发）
			resStart := time.Now()
			urls, rerr := be.ResolveImageURLs(ctx, res.ConversationID, res.FileIDs, res.SedimentIDs)
			resolveMs := time.Since(resStart).Milliseconds()
			if rerr != nil {
				o.Pool.Release(acc)
				return nil, fmt.Errorf("resolve image urls: %w", rerr)
			}
			// b64 模式：并发下载后流式编码
			var b64Data [][]byte
			var downloadMs, encodeMs int64
			if len(urls) > 0 {
				dlStart := time.Now()
				datas, derr := be.DownloadImages(ctx, urls)
				downloadMs = time.Since(dlStart).Milliseconds()
				if derr == nil {
					encStart := time.Now()
					for _, d := range datas {
						b64Data = append(b64Data, []byte(base64.StdEncoding.EncodeToString(d)))
					}
					encodeMs = time.Since(encStart).Milliseconds()
				}
			}
			o.Pool.Release(acc)
			stage := res.Stage
			stage.AccountPickMs = pickMs
			stage.ResolveMs = resolveMs
			stage.DownloadMs = downloadMs
			stage.EncodeMs = encodeMs
			stage.TotalMs += resolveMs + downloadMs + encodeMs
			return &GenerateResult{URLs: urls, B64: b64Data, Timing: stage}, nil
		}
		lastErr = err
		f := failure.Classify(err, 0, err.Error())
		if !f.SwitchAccount() {
			o.Pool.Release(acc)
			break
		}
		// 冷却
		o.Pool.Cooldown(acc, time.Now().Add(30*time.Second))
		o.Pool.Release(acc)
		excluded[acc.Token] = true
	}
	if lastErr != nil {
		return nil, fmt.Errorf("all accounts failed: %w", lastErr)
	}
	return nil, fmt.Errorf("no available account")
}

// StreamText 文本对话流（P2.1）：账号轮换 + 文本 SSE delta。
// onDelta 每个文本增量调用一次；返回聚合全文与 conversation_id。
// 对等 stream_text_deltas（账号轮换语义；token 失效换号逻辑在 failure 分类后触发）。
func (o *Orchestrator) StreamText(ctx context.Context, req TextRequest, onDelta func(string)) (string, string, error) {
	if req.Model == "" {
		req.Model = "auto"
	}
	attempts := o.Config.MaxAttempts
	if attempts == 0 {
		attempts = 3
	}
	var lastErr error
	excluded := make(map[string]bool)
	parser := NewTextStreamParser(assistantHistoryText(req.Messages))
	for attempt := 0; attempt < attempts; attempt++ {
		sel := account.Selector{Excluded: excluded, MaxInflight: o.Config.Concurrency}
		acc := o.Pool.Pick(sel)
		if acc == nil {
			break
		}
		be, err := o.getBackend(acc)
		if err != nil {
			o.Pool.Release(acc)
			lastErr = fmt.Errorf("create backend: %w", err)
			continue
		}
		_ = o.Pool.EnsureFreshToken(acc)
		genStart := time.Now()
		body, err := be.StartTextConversation(ctx, req.Messages, req.Model, req.ThinkingEffort, nil)
		if err != nil {
			o.recordTextMetrics(req, genStart, err)
			lastErr = err
			f := failure.Classify(err, 0, err.Error())
			if !f.SwitchAccount() {
				o.Pool.Release(acc)
				break
			}
			o.Pool.Cooldown(acc, time.Now().Add(30*time.Second))
			o.Pool.Release(acc)
			excluded[acc.Token] = true
			continue
		}
		convID, streamErr := backend.StreamTextPayloads(ctx, body, 300*time.Second, func(payload string) {
			if delta := parser.Feed(payload); delta != "" && onDelta != nil {
				onDelta(delta)
			}
		})
		_ = body.Close()
		o.recordTextMetrics(req, genStart, streamErr)
		if o.Logger != nil {
			o.Logger.Add(&logsvc.LoggedCall{
				ID:        utils.NewUUID(),
				Model:     req.Model,
				Status:    statusOf(streamErr),
				CreatedAt: time.Now(),
				Attempts:  []logsvc.Attempt{{AccountID: acc.Email, Code: codeOf(streamErr)}},
			})
		}
		if streamErr == nil || parser.Text != "" {
			o.Pool.Release(acc)
			return parser.Text, convID, streamErr
		}
		lastErr = streamErr
		f := failure.Classify(streamErr, 0, streamErr.Error())
		if !f.SwitchAccount() {
			o.Pool.Release(acc)
			break
		}
		o.Pool.Cooldown(acc, time.Now().Add(30*time.Second))
		o.Pool.Release(acc)
		excluded[acc.Token] = true
	}
	if lastErr != nil {
		return "", "", fmt.Errorf("all accounts failed: %w", lastErr)
	}
	return "", "", fmt.Errorf("no available account")
}

// assistantHistoryText assistant 历史回显前缀（对等 assistant_history_text）。
func assistantHistoryText(messages []map[string]any) string {
	var b strings.Builder
	for _, m := range messages {
		if role, _ := m["role"].(string); role == "assistant" {
			b.WriteString(MessageText(m["content"]))
		}
	}
	return b.String()
}

// recordTextMetrics 文本调用指标（endpoint=/v1/chat/completions）。
func (o *Orchestrator) recordTextMetrics(req TextRequest, start time.Time, err error) {
	if o.Metrics == nil {
		return
	}
	o.Metrics.Record(metrics.CallEvent{
		Status:    metricsStatusOf(err),
		Endpoint:  "/v1/chat/completions",
		Model:     req.Model,
		ErrorCode: metricsCodeOf(err),
		Duration:  float64(time.Since(start).Milliseconds()),
		At:        time.Now(),
	})
}

func utilsCheckContent(prompt string) error {
	if ok, _ := filter.IsAllowed(prompt); !ok {
		return &filter.ContentFilterError{Code: "content_policy_violation"}
	}
	return nil
}
func statusOf(err error) string {
	if err == nil {
		return "success"
	}
	return "error"
}

// metricsStatusOf/metricsCodeOf 仪表盘口径（P1.7）：失败码透传 error_code 桶。
func metricsStatusOf(err error) string {
	return statusOf(err)
}

func metricsCodeOf(err error) string {
	if err == nil {
		return ""
	}
	if f, ok := err.(interface{ Code() string }); ok {
		return f.Code()
	}
	return "upstream_error"
}
func codeOf(err error) string {
	if err == nil {
		return "ok"
	}
	return "upstream_error"
}
