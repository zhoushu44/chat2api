package failure

import (
	"errors"
	"strings"
)

// FailurePolicy 对应 Python FailurePolicy
type FailurePolicy struct {
Scope      string
Capability *string
Retryable  bool
StatusCode int
ErrorType  string
}

func strPtr(s string) *string { return &s }

// ImageFailure 完整失败对象
type ImageFailure struct {
Code          string
Scope         string
Capability    *string
Retryable     bool
RetryAfter    *int
StatusCode    int
ErrorType     string
RawDetail     any
PublicDetail  string
AccountFailure bool
}

func (f ImageFailure) SwitchAccount() bool { return f.Scope == "account" || f.Scope == "transient" && f.Code != "upstream_rate_limited" }
func (f ImageFailure) VerifyAccount() bool { return f.Scope == "account" }

var policies = map[string]FailurePolicy{
"upstream_error":               {Scope: "transient", Retryable: false, StatusCode: 502, ErrorType: "server_error"},
"internal_error":               {Scope: "internal", Retryable: false, StatusCode: 500, ErrorType: "server_error"},
"upstream_unavailable":         {Scope: "transient", Retryable: true, StatusCode: 502, ErrorType: "server_error"},
"upstream_connection_failed":   {Scope: "transient", Retryable: true, StatusCode: 502, ErrorType: "server_error"},
"upstream_connection_timeout":  {Scope: "transient", Retryable: true, StatusCode: 504, ErrorType: "server_error"},
"upstream_rate_limited":        {Scope: "transient", Capability: strPtr("image_generation"), Retryable: false, StatusCode: 429, ErrorType: "rate_limit_error"},
// account_rate_limited：429 限流（非额度耗尽）。按「账号级 + 冷却」处理：
// 不做死号判定，只让该号短暂冷却并切换到其它号重试，避免限流把可用账号打光。
"account_rate_limited":         {Scope: "account", Capability: strPtr("image_generation"), Retryable: false, StatusCode: 429, ErrorType: "rate_limit_error"},
// upstream_forbidden：403 但账号未停用（风控/权限拒绝）。按「账号级 + 长冷却」处理：
// 此前 403 落到 default→upstream_error(transient)，会立刻换号且该号不隔离，
// 导致同一个号被反复选中、反复 403。现在改为冷却隔离该号。
"upstream_forbidden":           {Scope: "account", Capability: strPtr("image_generation"), Retryable: false, StatusCode: 403, ErrorType: "permission_error"},
"image_poll_timeout":           {Scope: "transient", Capability: strPtr("image_generation"), Retryable: false, StatusCode: 502, ErrorType: "server_error"},
"image_stream_timeout":         {Scope: "transient", Capability: strPtr("image_generation"), Retryable: false, StatusCode: 502, ErrorType: "server_error"},
"image_stream_interrupted":     {Scope: "transient", Capability: strPtr("image_generation"), Retryable: false, StatusCode: 502, ErrorType: "server_error"},
"image_tool_error":             {Scope: "account", Capability: strPtr("image_generation"), Retryable: false, StatusCode: 502, ErrorType: "server_error"},
"image_quota_exhausted":        {Scope: "account", Capability: strPtr("image_generation"), Retryable: false, StatusCode: 429, ErrorType: "insufficient_quota"},
"file_upload_throttled":        {Scope: "account", Capability: strPtr("file_upload"), Retryable: true, StatusCode: 429, ErrorType: "rate_limit_error"},
"auth_invalid":                 {Scope: "account", Capability: strPtr("auth"), Retryable: false, StatusCode: 401, ErrorType: "authentication_error"},
"content_policy_violation":     {Scope: "request", Retryable: false, StatusCode: 400, ErrorType: "invalid_request_error"},
"invalid_image_input":          {Scope: "request", Retryable: false, StatusCode: 400, ErrorType: "invalid_request_error"},
"upstream_text_reply":          {Scope: "request", Retryable: false, StatusCode: 400, ErrorType: "invalid_request_error"},
"no_image_generated":           {Scope: "request", Retryable: false, StatusCode: 502, ErrorType: "server_error"},
"unsupported_model":            {Scope: "account", Retryable: true, StatusCode: 400, ErrorType: "invalid_request_error"},
"image_download_failed":        {Scope: "delivery", Retryable: false, StatusCode: 502, ErrorType: "server_error"},
"task_interrupted":             {Scope: "request", Retryable: false, StatusCode: 503, ErrorType: "server_error"},
"no_available_account":         {Scope: "transient", Retryable: false, StatusCode: 503, ErrorType: "server_error"},
"insufficient_quota":           {Scope: "account", Capability: strPtr("image_generation"), Retryable: false, StatusCode: 429, ErrorType: "insufficient_quota"},
}

// PolicyCount 与策略表条数对齐（原 22 条 + account_rate_limited = 23）。
const PolicyCount = 24

func New(code string, raw any) ImageFailure {
p, ok := policies[code]
if !ok {
p = policies["upstream_error"]
}
return ImageFailure{
Code: code, Scope: p.Scope, Capability: p.Capability, Retryable: p.Retryable,
StatusCode: p.StatusCode, ErrorType: p.ErrorType, RawDetail: raw,
}
}

// Classify 根据错误文本/状态码分类（简化版，覆盖测试用例）
func Classify(err error, statusCode int, body string) ImageFailure {
	msg := ""
	if err != nil {
		msg = err.Error()
	}
	// 结构化上游错误：按真实状态码归类（errors.As 解 wrap 链；文本可能不含关键词）
	var sc interface{ UpstreamStatus() int }
	if errors.As(err, &sc) && sc.UpstreamStatus() == 401 {
		return New("auth_invalid", msg)
	}
	msg = strings.ToLower(msg + " " + strings.ToLower(body))
	switch {
	case strings.Contains(msg, "unauthorized") || strings.Contains(msg, "invalid_api_key") || statusCode == 401:
		return New("auth_invalid", msg)
	// 账号被上游停用（403 + account_deactivated）：属于真死号，按 auth 失效处理，
	// 走「待重登」而不是被当成临时错误反复重试。
	case strings.Contains(msg, "account_deactivated") || strings.Contains(msg, "deleted or deactivated"):
		return New("auth_invalid", msg)
	// 403 但账号未停用（风控/权限拒绝）：账号级 + 长冷却，避免反复打同一个号。
	case statusCode == 403 || strings.Contains(msg, "forbidden"):
		return New("upstream_forbidden", msg)
	case strings.Contains(msg, "insufficient_quota") || strings.Contains(msg, "quota_exhausted"):
		return New("insufficient_quota", msg)
	case strings.Contains(msg, "rate limit") || strings.Contains(msg, "rate_limited") || statusCode == 429 && strings.Contains(msg, "quota"):
		return New("image_quota_exhausted", msg)
	case statusCode == 429:
		return New("account_rate_limited", msg)
	case strings.Contains(msg, "content_policy") || strings.Contains(msg, "content policy") || strings.Contains(msg, "content filter") || strings.Contains(msg, "policy_violation") || strings.Contains(msg, "policy violation") || strings.Contains(msg, "safety"):
		return New("content_policy_violation", msg)
	case strings.Contains(msg, "decode image base64") || strings.Contains(msg, "illegal base64") || strings.Contains(msg, "invalid_image_input"):
		return New("invalid_image_input", msg)
	case strings.Contains(msg, "no_image_generated"):
		return New("no_image_generated", msg)
	case strings.Contains(msg, "upstream_text_reply"):
		return New("upstream_text_reply", msg)
	case strings.Contains(msg, "unsupported_model") || strings.Contains(msg, "unsupported model") || strings.Contains(msg, "model_not_found") || strings.Contains(msg, "model not found"):
		return New("unsupported_model", msg)
	case strings.Contains(msg, "no available account") || strings.Contains(msg, "no_available_account") || strings.Contains(msg, "no account"):
		return New("no_available_account", msg)
	case strings.Contains(msg, "download failed") || strings.Contains(msg, "download_failed") || strings.Contains(msg, "failed to download"):
		return New("image_download_failed", msg)
	case strings.Contains(msg, "task_interrupted") || strings.Contains(msg, "task interrupted"):
		return New("task_interrupted", msg)
case strings.Contains(msg, "timeout") || strings.Contains(msg, "timed out"):
if strings.Contains(msg, "poll") {
return New("image_poll_timeout", msg)
}
if strings.Contains(msg, "stream") {
return New("image_stream_timeout", msg)
}
return New("upstream_connection_timeout", msg)
case strings.Contains(msg, "interrupted") || strings.Contains(msg, "stream_interrupted"):
return New("image_stream_interrupted", msg)
case strings.Contains(msg, "connection") || strings.Contains(msg, "unavailable"):
return New("upstream_unavailable", msg)
case strings.Contains(msg, "tool_error") || strings.Contains(msg, "async_task"):
return New("image_tool_error", msg)
default:
return New("upstream_error", msg)
}
}
