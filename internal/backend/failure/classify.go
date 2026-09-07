package failure

import (
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
"unsupported_model":            {Scope: "request", Retryable: false, StatusCode: 400, ErrorType: "invalid_request_error"},
"image_download_failed":        {Scope: "delivery", Retryable: false, StatusCode: 502, ErrorType: "server_error"},
"task_interrupted":             {Scope: "request", Retryable: false, StatusCode: 503, ErrorType: "server_error"},
"no_available_account":         {Scope: "transient", Retryable: false, StatusCode: 503, ErrorType: "server_error"},
"insufficient_quota":           {Scope: "account", Capability: strPtr("image_generation"), Retryable: false, StatusCode: 429, ErrorType: "insufficient_quota"},
}

// PolicyCount 与 Python FAILURE_POLICIES 的 22 条对齐（P1.6 验收用）。
const PolicyCount = 22

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
	msg = strings.ToLower(msg + " " + strings.ToLower(body))
	switch {
	case strings.Contains(msg, "unauthorized") || strings.Contains(msg, "invalid_api_key") || statusCode == 401:
		return New("auth_invalid", msg)
	case strings.Contains(msg, "insufficient_quota") || strings.Contains(msg, "quota_exhausted"):
		return New("insufficient_quota", msg)
	case strings.Contains(msg, "rate limit") || strings.Contains(msg, "rate_limited") || statusCode == 429 && strings.Contains(msg, "quota"):
		return New("image_quota_exhausted", msg)
	case statusCode == 429:
		return New("upstream_rate_limited", msg)
	case strings.Contains(msg, "content_policy") || strings.Contains(msg, "content policy") || strings.Contains(msg, "content filter") || strings.Contains(msg, "policy_violation") || strings.Contains(msg, "policy violation") || strings.Contains(msg, "safety"):
		return New("content_policy_violation", msg)
	case strings.Contains(msg, "decode image base64") || strings.Contains(msg, "illegal base64") || strings.Contains(msg, "invalid_image_input"):
		return New("invalid_image_input", msg)
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
