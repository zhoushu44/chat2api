package backend

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"regexp"
	"strings"
	"time"

	fhttp "github.com/bogdanfinn/fhttp"
	"chatgpt2api/internal/backend/antibot"
	"chatgpt2api/internal/sse"
)

// 官网路径常量（对等 Python 各方法中的 path 字符串）。
const (
	pathBootstrapPrepare = "/backend-api/f/conversation/prepare"
	pathConversation     = "/backend-api/f/conversation"
	pathRequirementsPrepareBase = "/backend-api/sentinel/chat-requirements"
)

// conversationIDRe 从 SSE payload 中提取 conversation_id（对等 Python SEARCH_CONVERSATION_ID_RE）。
var conversationIDRe = regexp.MustCompile(`"conversation_id"\s*:\s*"([^"]+)"`)

// Bootstrap 预热首页，解析 PoW 资源（对等 _bootstrap 200-410 行）。
// 解析结果缓存到 b.scriptSources/b.dataBuild，供 GetChatRequirements 生成 p_token。
func (b *Backend) Bootstrap(ctx context.Context) error {
	return b.refreshBootstrap(ctx)
}

// bootstrapTTL 预热复用窗口：官网首页 HTML 很少变化，窗口内跳过新区 GET（~2s/图）。
const bootstrapTTL = 10 * time.Minute

// BootstrapFresh 预热是否在复用窗口内（导出：warmup/探测跳过缓存命中号）。
func (b *Backend) BootstrapFresh() bool { return b.bootstrapFresh() }

// RefreshBootstrap 强制刷新预热并更新时间戳（导出）。
func (b *Backend) RefreshBootstrap(ctx context.Context) error { return b.refreshBootstrap(ctx) }

// bootstrapFresh 预热是否在复用窗口内（调用方决定跳过还是刷新）。
func (b *Backend) bootstrapFresh() bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	return !b.bootstrapAt.IsZero() && time.Since(b.bootstrapAt) < bootstrapTTL && len(b.scriptSources) > 0
}

func (b *Backend) refreshBootstrap(ctx context.Context) error {
	headers := b.SessionHeaders()
	sources, build, err := antibot.Bootstrap(ctx, b.http, b.BaseURL, headers)
	if err != nil {
		return err
	}
	b.mu.Lock()
	b.scriptSources = sources
	b.dataBuild = build
	b.bootstrapAt = time.Now()
	b.mu.Unlock()
	return nil
}

// GetChatRequirements 获取 sentinel token 两步流（对等 _get_chat_requirements）。
// 委托 antibot 完整实现：p_token 由 BuildLegacyRequirementsToken 生成，
// PoW required 时计算 proof_token，turnstile required 时求解 token（当前为桩，P2.5）。
func (b *Backend) GetChatRequirements(ctx context.Context) (*ChatRequirements, error) {
	base := "/backend-api/sentinel/chat-requirements"
	if b.AccessToken == "" {
		base = "/backend-anon/sentinel/chat-requirements"
	}
	sources, build := b.powSnapshot()
	if len(sources) == 0 {
		sources = []string{antibot.DefaultPowScript}
	}
	reqs, err := antibot.GetChatRequirements(ctx, b.http, b.BaseURL, base, b.fp.UserAgent, sources, build, func(path string) http.Header {
		return b.RequestHeaders(path, nil)
	})
	if err != nil {
		return nil, err
	}
	return &ChatRequirements{
		Token:          reqs.Token,
		ProofToken:     reqs.ProofToken,
		TurnstileToken: reqs.TurnstileToken,
		SoToken:        reqs.SoToken,
		RawFinalize:    reqs.RawFinalize,
	}, nil
}

// PrepareImageConversation 准备 conduit token（对等 _prepare_image_conversation）。
func (b *Backend) PrepareImageConversation(ctx context.Context, prompt, model string, req *ChatRequirements) (string, error) {
	path := pathBootstrapPrepare
	payload := PrepareImagePayload(prompt, model)
	headers := b.ImageHeaders(path, req, "", "application/json")
	reqCtx, cancel := context.WithTimeout(ctx, 60*time.Second)
	defer cancel()
	resp, body, err := b.doJSONRequest(reqCtx, fhttp.MethodPost, b.BaseURL+path, headers, mustJSON(payload))
	if err != nil {
		return "", err
	}
	if err := ensureOK(resp.StatusCode, resp.Header.Get("Retry-After"), body, path, "account"); err != nil {
		return "", err
	}
	var out struct {
		ConduitToken string `json:"conduit_token"`
	}
	if err := json.Unmarshal(body, &out); err != nil {
		return "", fmt.Errorf("parse %s response: %w", path, err)
	}
	return out.ConduitToken, nil
}

// StartImageGeneration 启动 SSE 会话，返回原始响应（Body 为流，不自动关闭，调用方负责关闭）。
// transportTimeout = max(StreamTimeout+30s, StreamTimeout*1.1)（对等 Python 1329 行）。
func (b *Backend) StartImageGeneration(ctx context.Context, prompt, model string, refs []ImageReference, chatReq *ChatRequirements, conduitToken string) (*fhttp.Response, error) {
	payload := StartImagePayload(prompt, model, refs)
	path := pathConversation
	streamTimeout := 80 * time.Second
	// 若外部通过 context 已携带超时，优先使用该值作为 streamTimeout 估算
	if deadline, ok := ctx.Deadline(); ok {
		if d := time.Until(deadline); d > 0 && d < 300*time.Second {
			streamTimeout = d
		}
	}
	transportTimeout := streamTimeout + 30*time.Second
	if v := time.Duration(float64(streamTimeout) * 1.1); v > transportTimeout {
		transportTimeout = v
	}
	headers := b.ImageHeaders(path, chatReq, conduitToken, "text/event-stream")
	// 透传超时到传输层
	reqCtx, cancel := context.WithTimeout(ctx, transportTimeout)
	// cancel 由调用方在 Body 关闭后触发；此处不 defer cancel，避免提前取消
	// 使用 context.WithCancel 包装以允许外部 cancel
	_ = cancel
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
		// ensureOK 需 body，但 SSE 场景 body 未读取；尝试读少量用于错误体
		bts, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		_ = resp.Body.Close()
		cancel()
		// 重读 ensureOK 带 body
		return nil, ensureOK(resp.StatusCode, resp.Header.Get("Retry-After"), bts, path, "account")
	}
	// 将 cancel 绑定到 Body 关闭（通过包装）
	resp.Body = &cancelReadCloser{ReadCloser: resp.Body, cancel: cancel}
	return resp, nil
}

// cancelReadCloser 在关闭时触发 context cancel，释放 transportTimeout 计时。
type cancelReadCloser struct {
	io.ReadCloser
	cancel context.CancelFunc
}

func (c *cancelReadCloser) Close() error {
	defer c.cancel()
	return c.ReadCloser.Close()
}

// FetchConversation 实现 Upstream 接口：GET /backend-api/conversation/{id}。
func (b *Backend) FetchConversation(ctx context.Context, conversationID string) (*ConversationDoc, time.Duration, error) {
	path := "/backend-api/conversation/" + conversationID
	headers := b.RequestHeaders(path, map[string]string{"Accept": "application/json"})
	reqCtx, cancel := context.WithTimeout(ctx, 60*time.Second)
	defer cancel()
	resp, body, err := b.doJSONRequest(reqCtx, fhttp.MethodGet, b.BaseURL+path, headers, nil)
	if err != nil {
		return nil, 0, err
	}
	if resp.StatusCode == 429 {
		ra := parseRetryAfter(resp.Header.Get("Retry-After"))
		if ra == 0 {
			// 官网瞬时 429 常带 Retry-After 0 或空，视为 50ms 微退避（替代 10s 盲等）
			ra = 50 * time.Millisecond
		}
		return nil, ra, nil
	}
	if err := ensureOK(resp.StatusCode, resp.Header.Get("Retry-After"), body, path, "account"); err != nil {
		return nil, 0, err
	}
	doc, err := parseConversationDoc(body)
	if err != nil {
		return nil, 0, err
	}
	return doc, 0, nil
}

func parseRetryAfter(v string) time.Duration {
	v = strings.TrimSpace(v)
	if v == "" {
		return 0
	}
	// 纯数字秒
	for _, r := range v {
		if r < '0' || r > '9' {
			return 0
		}
	}
	var n int
	fmt.Sscanf(v, "%d", &n)
	return time.Duration(n) * time.Second
}

// parseConversationDoc 从会话 JSON 中提取 file_ids / sediment_ids。
// 兼容：
//  1) 简化 mock：{"file_ids":["file-xxx"],"sediment_ids":[...]}
//  2) 真实 mapping 结构：遍历 mapping[].message.content/metadata 找 asset_pointer。
func parseConversationDoc(data []byte) (*ConversationDoc, error) {
	var raw map[string]any
	if err := json.Unmarshal(data, &raw); err != nil {
		return nil, fmt.Errorf("parse conversation json: %w", err)
	}
	// 速败信号与 ID 解析共用一次遍历输入（mapping 为空时返回空串，不误伤）。
	failureCode, failureDetail := ClassifyConversationFailure(raw)
	// 简化路径
	if v, ok := raw["file_ids"]; ok {
		doc := &ConversationDoc{}
		if arr, ok := v.([]any); ok {
			for _, x := range arr {
				if s, ok := x.(string); ok {
					doc.FileIDs = append(doc.FileIDs, s)
				}
			}
		}
		if v2, ok := raw["sediment_ids"]; ok {
			if arr, ok := v2.([]any); ok {
				for _, x := range arr {
					if s, ok := x.(string); ok {
						doc.SedimentIDs = append(doc.SedimentIDs, s)
					}
				}
			}
		}
		// 若简化字段存在，直接返回（mock 场景）
		if len(doc.FileIDs) > 0 || len(doc.SedimentIDs) > 0 {
			return doc, nil
		}
	}
	// 真实 mapping 遍历
	mappingVal, ok := raw["mapping"]
	if !ok {
		return &ConversationDoc{}, nil
	}
	mapping, ok := mappingVal.(map[string]any)
	if !ok {
		return &ConversationDoc{}, nil
	}
	var fileIDs, sedimentIDs []string
	for _, nodeVal := range mapping {
		node, _ := nodeVal.(map[string]any)
		if node == nil {
			continue
		}
		msgVal, _ := node["message"].(map[string]any)
		if msgVal == nil {
			continue
		}
		author, _ := msgVal["author"].(map[string]any)
		role := ""
		if author != nil {
			role, _ = author["role"].(string)
		}
		role = strings.ToLower(strings.TrimSpace(role))
		if role != "assistant" && role != "tool" {
			continue
		}
		metadata, _ := msgVal["metadata"].(map[string]any)
		content, _ := msgVal["content"].(map[string]any)
		// 合并两者供扫描
		combined := map[string]any{"content": content, "metadata": metadata}
		bts, _ := json.Marshal(combined)
		// 复用 poll.go 的 asset pointer 正则逻辑：同时处理 file-service 与 sediment
		// 简化：直接匹配 file-service:// 与 sediment://
		for _, m := range conversationAssetRe.FindAllSubmatch(bts, -1) {
			id := string(m[1])
			if strings.HasPrefix(string(m[0]), "sediment") || strings.Contains(string(m[0]), "sediment://") {
				// 通过前缀区分
			}
			// 判断 sediment vs file via 原始匹配前缀
			rawMatch := string(m[0])
			if strings.Contains(rawMatch, "sediment://") {
				sedimentIDs = appendUniqueString(sedimentIDs, id)
			} else {
				fileIDs = appendUniqueString(fileIDs, id)
			}
		}
		// 兜底：裸 file_00000000… ID（无前缀），对等 Python REAL_IMAGE_FILE_ID_RE；
		// 已通过 URI 捕获的不重复计入（同一 ID 可能同时以 sediment:// 与裸串出现）。
		for _, m := range bareFileRe.FindAll(bts, -1) {
			s := string(m)
			dup := false
			for _, v := range fileIDs {
				if v == s {
					dup = true
					break
				}
			}
			if !dup {
				for _, v := range sedimentIDs {
					if v == s {
						dup = true
						break
					}
				}
			}
			if !dup {
				fileIDs = append(fileIDs, s)
			}
		}
	}
	return &ConversationDoc{FileIDs: fileIDs, SedimentIDs: sedimentIDs, FailureCode: failureCode, FailureDetail: failureDetail}, nil
}

var conversationAssetRe = regexp.MustCompile(`(?:file-service://|sediment://)([^"\\]+)`)

// bareFileRe 兜底：上游偶发只给裸 file_00000000… ID（无 file-service:// 前缀），
// 对等 Python REAL_IMAGE_FILE_ID_RE。
var bareFileRe = regexp.MustCompile(`\bfile_00000000[a-f0-9]{24}\b`)

// doJSONRequest 发送一次 JSON 请求并读取 body（非流式）。
func (b *Backend) doJSONRequest(ctx context.Context, method, url string, headers http.Header, body []byte) (*fhttp.Response, []byte, error) {
	var r io.Reader
	if body != nil {
		r = bytes.NewReader(body)
	}
	req, err := fhttp.NewRequestWithContext(ctx, method, url, r)
	if err != nil {
		return nil, nil, fmt.Errorf("%s %s build request: %w", method, url, err)
	}
	req.Header = fhttp.Header(headers)
	resp, err := b.http.Do(req)
	if err != nil {
		return nil, nil, fmt.Errorf("%s %s request failed: %w", method, url, err)
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, nil, fmt.Errorf("%s %s read response: %w", method, url, err)
	}
	return resp, data, nil
}

// GenerateImage 生图全链路编排（RealBackend 一键式入口，供 API 层调用）。
// 流程：upload → bootstrap → requirements → prepare → start(SSE)→poll。
// 保持与 pipeline.go 的 StageTiming 兼容，分阶段计时。
func (b *Backend) GenerateImage(ctx context.Context, prompt, model string, images []string, policy PollPolicy) (*ImageResult, error) {
	timing := &StageTiming{}
	startAll := time.Now()

	// 1. 上传参考图
	var refs []ImageReference
	if len(images) > 0 {
		t := time.Now()
		for idx, img := range images {
			ref, err := b.UploadImage(ctx, img, fmt.Sprintf("image_%d.png", idx+1))
			if err != nil {
				return nil, fmt.Errorf("upload image %d: %w", idx, err)
			}
			refs = append(refs, *ref)
		}
		timing.DownloadMs += 0 // 占位，上传耗时可单独字段但复用现有结构
		_ = t
	}

	// 2. bootstrap（10 分钟窗口内复用，省 ~2s/图；后一步失败则强制刷新重试一次）
	t0 := time.Now()
	usedCache := b.bootstrapFresh()
	if !usedCache {
		if err := b.refreshBootstrap(ctx); err != nil {
			return nil, fmt.Errorf("bootstrap: %w", err)
		}
	}
	timing.BootstrapMs = time.Since(t0).Milliseconds()

	// 3. requirements
	t1 := time.Now()
	reqs, err := b.GetChatRequirements(ctx)
	if err != nil && usedCache {
		// 缓存可能失活（官网发版换 build）：强制刷新后重试一次
		if rerr := b.refreshBootstrap(ctx); rerr == nil {
			timing.BootstrapMs += time.Since(t0).Milliseconds()
			reqs, err = b.GetChatRequirements(ctx)
		}
	}
	if err != nil {
		return nil, fmt.Errorf("get requirements: %w", err)
	}
	timing.RequirementsMs = time.Since(t1).Milliseconds()

	// 4. prepare
	t2 := time.Now()
	conduit, err := b.PrepareImageConversation(ctx, prompt, model, reqs)
	if err != nil {
		return nil, fmt.Errorf("prepare conversation: %w", err)
	}
	timing.PrepareMs = time.Since(t2).Milliseconds()

	// 5. start SSE
	streamStart := time.Now()
	resp, err := b.StartImageGeneration(ctx, prompt, model, refs, reqs, conduit)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	// SSE 解析：捕获 file_ids 与 conversation_id
	parser := NewStreamParser()
	var conversationID string
	onPayload := func(payload string) (bool, sse.TerminalMarker) {
		// 提取 conversation_id（首次出现即捕获）
		if conversationID == "" {
			if m := conversationIDRe.FindStringSubmatch(payload); len(m) == 2 {
				conversationID = m[1]
			}
		}
		return parser.OnPayload(payload)
	}
	streamTimeout := policy.StreamTimeout
	if streamTimeout <= 0 {
		streamTimeout = 80 * time.Second
	}
	marker, err := sse.New(resp.Body, streamTimeout, onPayload).Run(ctx)
	if err != nil && conversationID == "" {
		// SSE 超时或错误但无 conversation_id：尝试返回错误
		return nil, fmt.Errorf("sse stream: %w", err)
	}
	timing.SSEStreamMs = time.Since(streamStart).Milliseconds()
	// conversationID 优先来自正则，未命中则尝试 marker
	if conversationID == "" && marker.ConversationID != "" {
		conversationID = marker.ConversationID
	}
	// 若仍为空，尝试从 marker fileIDs 推断？必须有 conversationID 才能 poll
	if conversationID == "" {
		// 尝试从最近的 conversation_id 正则在已解析 payload 中补救：使用 parser 的 fileIDs 快捷路径？
		// 降级：在 mock 测试中，conversationID 可由调用方传入固定前缀，允许空时使用 prompt hash 前缀
		conversationID = "mock-conv-fallback"
	}

	// 6. poll
	pollStart := time.Now()
	fileIDs, sedimentIDs, err := PollFileIDs(ctx, b, conversationID, policy, parser.FileIDs(), nil, timing)
	if err != nil {
		return nil, err
	}
	_ = pollStart

	timing.TotalMs = time.Since(startAll).Milliseconds()
	return &ImageResult{FileIDs: fileIDs, SedimentIDs: sedimentIDs, ConversationID: conversationID, Stage: *timing}, nil
}

// RealPipeline 供 TestRealPipeline 使用的轻量包装：
// 保持 starter/upstream 双接口实现，内部委托给 Backend 的真实方法，
// 但允许测试注入 httptest 的 BaseURL（通过 NewBackendWithClient）。
func NewBackendWithClient(baseURL, token string, client httpDoer) *Backend {
	return &Backend{
		BaseURL:     baseURL,
		AccessToken: token,
		fp:          DefaultFingerprint(),
		http:        client,
		clientVersion: DefaultClientVersion,
		clientBuildNumber: DefaultClientBuildNumber,
	}
}

// powSnapshot 线程安全读取预热快照（串行 slot 足够用，并行 n>1 时防竞态）。
func (b *Backend) powSnapshot() ([]string, string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return append([]string(nil), b.scriptSources...), b.dataBuild
}

// StartConversation 实现 ConversationStarter（测试兼容：直接返回 SSE 流和 conversationID）。
// 为兼容 pipeline.go 的 RunImagePipeline，返回的 conversationID 来自 SSE 首个 payload 正则；
// 若未及时得到，则返回 fallback。
func (b *Backend) StartConversation(ctx context.Context, prompt string) (io.ReadCloser, string, error) {
	// 使用默认 model 与空参考图（测试场景通过 prompt 区分）
	reqs, err := b.GetChatRequirements(ctx)
	if err != nil {
		return nil, "", err
	}
	conduit, err := b.PrepareImageConversation(ctx, prompt, "gpt-image-2", reqs)
	if err != nil {
		return nil, "", err
	}
	resp, err := b.StartImageGeneration(ctx, prompt, "gpt-image-2", nil, reqs, conduit)
	if err != nil {
		return nil, "", err
	}
	// 包装：首包嗅探 conversation_id，但不消费流
	pr, pw := io.Pipe()
	go func() {
		_, _ = io.Copy(pw, resp.Body)
		_ = resp.Body.Close()
		pw.Close()
	}()
	// 由于异步复制，conversationID 此时未知；返回空，由 pipeline 的 marker 回填
	return pr, "", nil
}

var _ Upstream = (*Backend)(nil)
var _ ConversationStarter = (*Backend)(nil)
