package backend

import (
	"encoding/json"
	"net/http"
	"strings"
	"time"

	"github.com/google/uuid"
)

// 客户端版本常量（对等 Python openai_backend_api.py:59-61）。
const (
	DefaultClientVersion     = "prod-a194cd50d4416d3c0b47c740f206b12ce60f5887"
	DefaultClientBuildNumber = "6708908"
	DefaultPowScript         = "https://chatgpt.com/backend-api/sentinel/sdk.js"
	CodexImageModel          = "codex-gpt-image-2"
)

// 模型映射常量（对等 utils/helper.py:21-22）。
var (
	BaseImageModels     = map[string]bool{"gpt-image-2": true, "codex-gpt-image-2": true}
	ImageModelPlanTypes = []string{"plus", "team", "pro"}
)

// Fingerprint 浏览器指纹（对等 Python _build_fp:303-330）。
// 账号可覆盖任意字段；未覆盖时用 Edge 143 默认值。
type Fingerprint struct {
	UserAgent       string `json:"user-agent"`
	Impersonate     string `json:"impersonate"`
	OaiDeviceID     string `json:"oai-device-id"`
	OaiSessionID    string `json:"oai-session-id"`
	SecChUa         string `json:"sec-ch-ua"`
	SecChUaMobile   string `json:"sec-ch-ua-mobile"`
	SecChUaPlatform string `json:"sec-ch-ua-platform"`
}

// DefaultFingerprint 生成默认指纹（设备/会话 ID 每实例随机，对等 setdefault new_uuid）。
func DefaultFingerprint() Fingerprint {
	return Fingerprint{
		UserAgent:       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0",
		Impersonate:     "chrome110",
		OaiDeviceID:     uuid.NewString(),
		OaiSessionID:    uuid.NewString(),
		SecChUa:         `"Microsoft Edge";v="143", "Chromium";v="143", "Not A(Brand";v="24"`,
		SecChUaMobile:   "?0",
		SecChUaPlatform: `"Windows"`,
	}
}

// Merge 账号级指纹覆盖（空值忽略，对等 fp.setdefault 语义）。
func (f Fingerprint) Merge(override map[string]string) Fingerprint {
	get := func(key string) (string, bool) {
		if v, ok := override[key]; ok && strings.TrimSpace(v) != "" {
			return strings.TrimSpace(v), true
		}
		// 小写键对齐（Python 侧键统一 lower）
		if v, ok := override[strings.ToLower(key)]; ok && strings.TrimSpace(v) != "" {
			return strings.TrimSpace(v), true
		}
		return "", false
	}
	if v, ok := get("user-agent"); ok {
		f.UserAgent = v
	}
	if v, ok := get("impersonate"); ok {
		f.Impersonate = v
	}
	if v, ok := get("oai-device-id"); ok {
		f.OaiDeviceID = v
	}
	if v, ok := get("oai-session-id"); ok {
		f.OaiSessionID = v
	}
	if v, ok := get("sec-ch-ua"); ok {
		f.SecChUa = v
	}
	if v, ok := get("sec-ch-ua-mobile"); ok {
		f.SecChUaMobile = v
	}
	if v, ok := get("sec-ch-ua-platform"); ok {
		f.SecChUaPlatform = v
	}
	return f
}

// SessionHeaders 会话级公共请求头（对等 __init__ 里 session.headers.update:256-281）。
// tls-client 要求顺序敏感头由其内部处理，这里只给值。
func (b *Backend) SessionHeaders() http.Header {
	h := http.Header{}
	h.Set("User-Agent", b.fp.UserAgent)
	h.Set("Origin", b.BaseURL)
	h.Set("Referer", b.BaseURL+"/")
	h.Set("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8,en-US;q=0.7")
	h.Set("Cache-Control", "no-cache")
	h.Set("Pragma", "no-cache")
	h.Set("Priority", "u=1, i")
	h.Set("Sec-Ch-Ua", b.fp.SecChUa)
	h.Set("Sec-Ch-Ua-Arch", `"x86"`)
	h.Set("Sec-Ch-Ua-Bitness", `"64"`)
	h.Set("Sec-Ch-Ua-Full-Version", `"143.0.3650.96"`)
	h.Set("Sec-Ch-Ua-Full-Version-List", `"Microsoft Edge";v="143.0.3650.96", "Chromium";v="143.0.7499.147", "Not A(Brand";v="24.0.0.0"`)
	h.Set("Sec-Ch-Ua-Mobile", b.fp.SecChUaMobile)
	h.Set("Sec-Ch-Ua-Model", `""`)
	h.Set("Sec-Ch-Ua-Platform", b.fp.SecChUaPlatform)
	h.Set("Sec-Ch-Ua-Platform-Version", `"19.0.0"`)
	h.Set("Sec-Fetch-Dest", "empty")
	h.Set("Sec-Fetch-Mode", "cors")
	h.Set("Sec-Fetch-Site", "same-origin")
	h.Set("OAI-Device-Id", b.fp.OaiDeviceID)
	h.Set("OAI-Session-Id", b.fp.OaiSessionID)
	h.Set("OAI-Language", "zh-CN")
	h.Set("OAI-Client-Version", b.clientVersion)
	h.Set("OAI-Client-Build-Number", b.clientBuildNumber)
	return h
}

// RequestHeaders 单请求头：会话头 + Bearer + web 端 target path/route（对等 _headers:332-341）。
func (b *Backend) RequestHeaders(path string, extra map[string]string) http.Header {
	h := b.SessionHeaders()
	if b.AccessToken != "" {
		h.Set("Authorization", "Bearer "+b.AccessToken)
	}
	h.Set("X-OpenAI-Target-Path", path)
	h.Set("X-OpenAI-Target-Route", path)
	for k, v := range extra {
		h.Set(k, v)
	}
	return h
}

// ImageHeaders 图片链路请求头（对等 _image_headers:798-812）。
func (b *Backend) ImageHeaders(path string, req *ChatRequirements, conduitToken, accept string) http.Header {
	if accept == "" {
		accept = "*/*"
	}
	extra := map[string]string{
		"Content-Type": "application/json",
		"Accept":       accept,
		"OpenAI-Sentinel-Chat-Requirements-Token": req.Token,
	}
	if req.ProofToken != "" {
		extra["OpenAI-Sentinel-Proof-Token"] = req.ProofToken
	}
	if conduitToken != "" {
		extra["X-Conduit-Token"] = conduitToken
	}
	if accept == "text/event-stream" {
		extra["X-Oai-Turn-Trace-Id"] = uuid.NewString()
	}
	return b.RequestHeaders(path, extra)
}

// ChatRequirements sentinel token 集合（对等 dataclass ChatRequirements:50-56）。
type ChatRequirements struct {
	Token          string
	ProofToken     string
	TurnstileToken string
	SoToken        string
	RawFinalize    map[string]any
}

// SplitImageModel 拆分模型名 → (plan_type, base_model)（对等 helper.py:113-125）。
// "gpt-image-2" → (nil, "gpt-image-2")；"plus-gpt-image-2" → ("plus", nil 但 codex 除外)。
func SplitImageModel(model string) (plan, base string) {
	normalized := strings.ToLower(strings.TrimSpace(model))
	if normalized == "" {
		return "", ""
	}
	if BaseImageModels[normalized] {
		return "", normalized
	}
	for _, p := range ImageModelPlanTypes {
		prefix := p + "-"
		if strings.HasPrefix(normalized, prefix) {
			base = normalized[len(prefix):]
			if base == CodexImageModel {
				return p, base
			}
			return "", ""
		}
	}
	return "", ""
}

// IsCodexImageModel 是否 codex 生图模型（对等 is_codex_image_model）。
func IsCodexImageModel(model string) bool {
	_, base := SplitImageModel(model)
	return base == CodexImageModel
}

// ImageModelSlug 标准图片模型名 → 底层 slug（对等 _image_model_slug:787-796）。
// gpt-image-2 → gpt-5-3；codex-gpt-image-2 → 原样；其他 → auto。
func ImageModelSlug(model string) string {
	_, base := SplitImageModel(model)
	switch base {
	case "":
		return "auto"
	case "gpt-image-2":
		return "gpt-5-3"
	case CodexImageModel:
		return base
	default:
		return "auto"
	}
}

// PrepareImagePayload /backend-api/f/conversation/prepare 请求体
// （对等 _prepare_image_conversation:1156-1177，字段 1:1）。
func PrepareImagePayload(prompt, model string) map[string]any {
	return map[string]any{
		"action":                  "next",
		"fork_from_shared_post":   false,
		"parent_message_id":       uuid.NewString(),
		"model":                   ImageModelSlug(model),
		"client_prepare_state":    "success",
		"timezone_offset_min":     -480,
		"timezone":                "Asia/Shanghai",
		"conversation_mode":       map[string]any{"kind": "primary_assistant"},
		"system_hints":            []string{"picture_v2"},
		"partial_query": map[string]any{
			"id":      uuid.NewString(),
			"author":  map[string]any{"role": "user"},
			"content": map[string]any{"content_type": "text", "parts": []string{prompt}},
		},
		"supports_buffering":      true,
		"supported_encodings":     []string{"v1"},
		"client_contextual_info":  map[string]any{"app_name": "chatgpt.com"},
	}
}

// ImageReference 已上传参考图元数据（对等 _upload_image 返回结构）。
type ImageReference struct {
	FileID   string `json:"file_id"`
	FileName string `json:"file_name"`
	FileSize int    `json:"file_size"`
	MimeType string `json:"mime_type"`
	Width    int    `json:"width"`
	Height   int    `json:"height"`
}

// StartImagePayload /backend-api/f/conversation SSE 请求体
// （对等 _start_image_generation:1261-1322，字段 1:1）。
func StartImagePayload(prompt, model string, references []ImageReference) map[string]any {
	// parts：参考图指针在前，prompt 在后（对等 Python 顺序）
	parts := make([]any, 0, len(references)+1)
	for _, ref := range references {
		parts = append(parts, map[string]any{
			"content_type":  "image_asset_pointer",
			"asset_pointer": "file-service://" + ref.FileID,
			"width":         ref.Width,
			"height":        ref.Height,
			"size_bytes":    ref.FileSize,
		})
	}
	parts = append(parts, prompt)

	var content map[string]any
	if len(references) > 0 {
		content = map[string]any{"content_type": "multimodal_text", "parts": parts}
	} else {
		content = map[string]any{"content_type": "text", "parts": []string{prompt}}
	}

	metadata := map[string]any{
		"developer_mode_connector_ids": []any{},
		"selected_github_repos":        []any{},
		"selected_all_github_repos":    false,
		"system_hints":                 []string{"picture_v2"},
		"serialization_metadata":       map[string]any{"custom_symbol_offsets": []any{}},
	}
	if len(references) > 0 {
		attachments := make([]any, 0, len(references))
		for _, ref := range references {
			attachments = append(attachments, map[string]any{
				"id":       ref.FileID,
				"mimeType": ref.MimeType,
				"name":     ref.FileName,
				"size":     ref.FileSize,
				"width":    ref.Width,
				"height":   ref.Height,
			})
		}
		metadata["attachments"] = attachments
	}

	return map[string]any{
		"action": "next",
		"messages": []any{map[string]any{
			"id":         uuid.NewString(),
			"author":     map[string]any{"role": "user"},
			"create_time": float64(time.Now().UnixMilli()) / 1000.0,
			"content":    content,
			"metadata":   metadata,
		}},
		"parent_message_id":              uuid.NewString(),
		"model":                          ImageModelSlug(model),
		"client_prepare_state":           "sent",
		"timezone_offset_min":            -480,
		"timezone":                       "Asia/Shanghai",
		"conversation_mode":              map[string]any{"kind": "primary_assistant"},
		"enable_message_followups":       true,
		"system_hints":                   []string{"picture_v2"},
		"supports_buffering":             true,
		"supported_encodings":            []string{"v1"},
		"client_contextual_info": map[string]any{
			"is_dark_mode":      false,
			"time_since_loaded": 1200,
			"page_height":       1072,
			"page_width":        1724,
			"pixel_ratio":       1.2,
			"screen_height":     1440,
			"screen_width":      2560,
			"app_name":          "chatgpt.com",
		},
		"paragen_cot_summary_display_override": "allow",
		"force_parallel_switch":                "auto",
	}
}

// PreparePayloadJSON / StartPayloadJSON 序列化（测试用，键序无关比对）。
func PreparePayloadJSON(prompt, model string) []byte    { return mustJSON(PrepareImagePayload(prompt, model)) }
func StartPayloadJSON(prompt, model string, refs []ImageReference) []byte {
	return mustJSON(StartImagePayload(prompt, model, refs))
}

func mustJSON(v any) []byte {
	b, err := json.Marshal(v)
	if err != nil {
		return []byte("{}")
	}
	return b
}
