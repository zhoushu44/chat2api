package backend

import (
	"context"
	"encoding/json"
	"fmt"
	"math/rand"
	"regexp"
	"sync"
	"time"

	"chatgpt2api/internal/sse"
)

// ErrPollTimeout 轮询预算耗尽（对等 Python ImagePollTimeoutError，可续轮询 can_resume_poll）。
var ErrPollTimeout = fmt.Errorf("image poll timeout")

// ConversationDoc 会话文档快照（仅保留轮询所需字段）。
type ConversationDoc struct {
	FileIDs     []string
	SedimentIDs []string
	// FailureCode/Detail 空轮询速败信号（对等 classify_conversation_failure，
	// parseConversationDoc 在解析 mapping 时一次性算好，轮询零额外请求）。
	FailureCode   string
	FailureDetail string
}

// Upstream 官网后端抽象：真实实现走 tls-client（M1.4 接入），mock 实现用于调度验证。
type Upstream interface {
	// FetchConversation 拉取会话文档。
	// retryAfter > 0 表示上游 429（调用方应等待后重试）；err 非nil 表示不可恢复错误。
	FetchConversation(ctx context.Context, conversationID string) (doc *ConversationDoc, retryAfter time.Duration, err error)
}

// PollFileIDs 事件驱动轮询状态机（M1 核心，替代 Python _poll_image_results 的定时器驱动）。
//
// 与 Python 版的关键差异（10s 预算来源）：
//  1. InitialWait 默认 300ms 而非 10s 盲等；429 按 Retry-After 微退避而非指数盲等
//  2. 空结果轮询自适应递增：Interval → 2×Interval → 3×Interval … 封顶 MaxInterval
//  3. settle 确认：file_ids 与上一次观测一致即返回（Python 固定等 5s）
//  4. 若 SSE 流内已解析出 asset pointer（initialFileIDs 非空），直接进入 settle 确认，
//     省去整个探测阶段
//
// timing 记录各阶段耗时（对等 Python _image_result_timing，用于验证 10s 预算）。
func PollFileIDs(
	ctx context.Context,
	up Upstream,
	conversationID string,
	policy PollPolicy,
	initialFileIDs, initialSedimentIDs []string,
	timing *StageTiming,
) (fileIDs, sedimentIDs []string, err error) {
	if timing == nil {
		timing = &StageTiming{}
	}
	deadline := time.Now().Add(policy.Timeout)

	fileIDs = uniqueStrings(initialFileIDs)
	sedimentIDs = uniqueStrings(initialSedimentIDs)

	// settle 确认状态：prevIDs/prevSediment 为上一次观测到的 file_ids/sediment 集合
	// 对等 Python hit_key=(file_ids, sediment_ids)：任一非空即命中，两组同时稳定才返回
	sawIDs := len(fileIDs) > 0 || len(sedimentIDs) > 0
	var prevIDs []string
	var prevSediment []string
	// prevFailCode 速败确认：同一失败信号连续两轮才触发
	var prevFailCode string
	if sawIDs {
		prevIDs = append([]string(nil), fileIDs...)
		prevSediment = append([]string(nil), sedimentIDs...)
	}

	// 首次等待：流内已有 ID → 直接等 Settle；否则等 InitialWait
	firstSleep := true
	wait := policy.InitialWait
	if sawIDs && policy.Settle > 0 {
		wait = policy.Settle
	}

	// 自适应间隔（空结果递增）
	interval := policy.Interval
	if interval <= 0 {
		interval = time.Second
	}

	for {
		remaining := time.Until(deadline)
		if remaining <= 0 {
			return nil, nil, fmt.Errorf("poll timeout (%s): %w", policy.Timeout, ErrPollTimeout)
		}
		if wait > 0 {
			sleepFor := wait
			if sleepFor > remaining {
				sleepFor = remaining
			}
			sleepStart := time.Now()
			select {
			case <-ctx.Done():
				return nil, nil, ctx.Err()
			case <-time.After(sleepFor):
			}
			// 首次等待计入 InitialWaitMs（10s 盲等 vs 300ms 的对比度量点）
			if firstSleep {
				timing.InitialWaitMs += msSince(sleepStart)
				firstSleep = false
			} else {
				timing.PollWaitMs += msSince(sleepStart)
			}
		}

		// 注：Python 每轮先查 backend tasks 做失败分类；Go 版该分类尚未移植，
		// 此处不发 tasks 查询（省 1 个 RTT/轮）。移植任务失败速败时再加回来。
		doc, retryAfter, err := up.FetchConversation(ctx, conversationID)
		timing.PollCount++
		if err != nil {
			return nil, nil, err
		}
		if retryAfter > 0 {
			// 429：按上游 Retry-After 退避 + 0~20ms jitter 避免惊群
			wait = retryAfter + time.Duration(rand.Intn(20))*time.Millisecond
			continue
		}
		if doc != nil {
			fileIDs = mergeUnique(fileIDs, doc.FileIDs)
			sedimentIDs = mergeUnique(sedimentIDs, doc.SedimentIDs)
		}

		if len(fileIDs) > 0 || len(sedimentIDs) > 0 {
			if !sawIDs {
				// 首次观测到 ID（file 或 sediment 任一）：等 Settle 后做稳定确认
				sawIDs = true
				prevIDs = append([]string(nil), fileIDs...)
				prevSediment = append([]string(nil), sedimentIDs...)
				wait = policy.Settle
				continue
			}
			if equalStringSets(prevIDs, fileIDs) && equalStringSets(prevSediment, sedimentIDs) {
				// 连续两次一致：结果稳定，立即返回（Python 固定 5s → Go ≤1s）
				return fileIDs, sedimentIDs, nil
			}
			// 集合变化（多图陆续就位）：重置确认窗口
			prevIDs = append([]string(nil), fileIDs...)
			prevSediment = append([]string(nil), sedimentIDs...)
			wait = policy.Settle
			continue
		}

		// 空结果：速败检查（对等 image_poll_conversation_failure）。
		// 当前轮已现终态失败证据（文本回复/额度/政策/工具错误）→ 抛明确错误，
		// 不再闷轮到超时。错误串首为分类码，供 failure.Classify 映射状态码。
		// 同一信号连续出现两次才触发（settle 式确认）：单帧过渡态（如工具调用
		// JSON 先终态、图片指针后到）不应误杀；确认仅多一轮（~1-2s），仍是秒级。
		if doc != nil && doc.FailureCode != "" {
			if doc.FailureCode == prevFailCode {
				return nil, nil, fmt.Errorf("%s: %s", doc.FailureCode, doc.FailureDetail)
			}
			prevFailCode = doc.FailureCode
		} else {
			prevFailCode = ""
		}

		// 空结果：自适应递增等待 1s→2s→3s…（封顶 MaxInterval）
		wait = interval
		if policy.MaxInterval > 0 && interval < policy.MaxInterval {
			interval += policy.Interval
			if interval > policy.MaxInterval {
				interval = policy.MaxInterval
			}
		}
	}
}

// ---- SSE 流内解析（对等 Python _is_image_stream_terminal_payload + asset pointer 提取）----

// assetPointerRe 官网 tool args 里的图片指针（file-service://file-xxx）。
// args 是转义后的 JSON 字符串，引号带反斜杠（\"asset_pointer\"），兼容两种形式。
var assetPointerRe = regexp.MustCompile(`\\?"asset_pointer\\?"\s*:\s*\\?"file-service://([^\\"]+)`)

// conversationIDRe 从 SSE payload 提取 conversation_id（对等 Python SEARCH_CONVERSATION_ID_RE）。
var conversationIDReParser = regexp.MustCompile(`"conversation_id"\s*:\s*"([^"]+)"`)

// StreamParser 增量解析 SSE payload：累计流内 file_ids、检测终止标记。
type StreamParser struct {
	mu             sync.Mutex
	fileIDs        []string
	seen           map[string]struct{}
	conversationID string
}

// NewStreamParser 创建流解析器。
func NewStreamParser() *StreamParser {
	return &StreamParser{seen: make(map[string]struct{})}
}

// OnPayload sse.Scanner 回调：返回 terminal=true 时立即结束 SSE 阶段。
func (p *StreamParser) OnPayload(payload string) (bool, sse.TerminalMarker) {
	terminal, ids := ParseStreamPayload([]byte(payload))
	p.mu.Lock()
	for _, id := range ids {
		if _, ok := p.seen[id]; !ok {
			p.seen[id] = struct{}{}
			p.fileIDs = append(p.fileIDs, id)
		}
	}
	if p.conversationID == "" {
		if m := conversationIDReParser.FindStringSubmatch(payload); len(m) == 2 {
			p.conversationID = m[1]
		}
	}
	idsCopy := append([]string(nil), p.fileIDs...)
	convID := p.conversationID
	p.mu.Unlock()
	if terminal {
		return true, sse.TerminalMarker{ConversationID: convID, FileIDs: idsCopy}
	}
	return false, sse.TerminalMarker{}
}

// ConversationID 返回流内捕获的 conversation_id。
func (p *StreamParser) ConversationID() string {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.conversationID
}

// FileIDs 流内累计的 file_ids 快照。
func (p *StreamParser) FileIDs() []string {
	p.mu.Lock()
	defer p.mu.Unlock()
	return append([]string(nil), p.fileIDs...)
}

// ParseStreamPayload 解析单帧 payload：
//   - terminal：帧内同时出现 finished_successfully=true 与 is_complete=true
//     （对等 Python 判定：标记出现即离开 SSE 阶段，不等连接关闭——
//     官网标记后连接保持打开，等关闭会耗尽整个 curl 超时）
//   - fileIDs：帧内 asset_pointer 引用的 file id（提前拿到，跳过轮询探测）
func ParseStreamPayload(payload []byte) (terminal bool, fileIDs []string) {
	var doc any
	if json.Unmarshal(payload, &doc) != nil {
		return false, nil
	}
	if hasCompletionMarker(doc) {
		terminal = true
	}
	for _, m := range assetPointerRe.FindAllSubmatch(payload, -1) {
		fileIDs = appendUniqueString(fileIDs, string(m[1]))
	}
	return terminal, fileIDs
}

// hasCompletionMarker 深度查找终止标记。
// 官网格式：message.status == "finished_successfully"（字符串）且 metadata.is_complete == true（布尔）。
func hasCompletionMarker(v any) bool {
	var finished, complete bool
	var walk func(x any)
	walk = func(x any) {
		switch t := x.(type) {
		case map[string]any:
			for k, val := range t {
				switch k {
				case "status":
					if s, ok := val.(string); ok && s == "finished_successfully" {
						finished = true
					}
				case "is_complete":
					if b, ok := val.(bool); ok && b {
						complete = true
					}
				}
				walk(val)
			}
		case []any:
			for _, it := range t {
				walk(it)
			}
		}
	}
	walk(v)
	return finished && complete
}

// ---- 小工具 ----

func msSince(t time.Time) int64 { return time.Since(t).Milliseconds() }

func uniqueStrings(in []string) []string {
	var out []string
	for _, s := range in {
		out = appendUniqueString(out, s)
	}
	return out
}

func appendUniqueString(list []string, s string) []string {
	for _, v := range list {
		if v == s {
			return list
		}
	}
	return append(list, s)
}

func mergeUnique(base, extra []string) []string {
	for _, s := range extra {
		base = appendUniqueString(base, s)
	}
	return base
}

func equalStringSets(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	set := make(map[string]struct{}, len(a))
	for _, s := range a {
		set[s] = struct{}{}
	}
	for _, s := range b {
		if _, ok := set[s]; !ok {
			return false
		}
	}
	return true
}
