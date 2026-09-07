package backend

import (
	"encoding/json"
	"strings"
	"testing"
)

// ---- 模型映射（对齐 Python split_image_model/_image_model_slug）----

func TestSplitImageModel(t *testing.T) {
	cases := []struct {
		in         string
		plan, base string
	}{
		{"", "", ""},
		{"gpt-image-2", "", "gpt-image-2"},
		{"GPT-IMAGE-2", "", "gpt-image-2"}, // 大小写归一
		{" codex-gpt-image-2 ", "", "codex-gpt-image-2"},
		{"plus-codex-gpt-image-2", "plus", "codex-gpt-image-2"},
		{"pro-codex-gpt-image-2", "pro", "codex-gpt-image-2"},
		{"team-codex-gpt-image-2", "team", "codex-gpt-image-2"},
		{"plus-gpt-image-2", "", ""},       // 非 codex 的 plan 前缀 → 不支持
		{"gpt-5", "", ""},                  // 文本模型非图片模型
		{"free-codex-gpt-image-2", "", ""}, // free 不在 plan 列表
	}
	for _, c := range cases {
		plan, base := SplitImageModel(c.in)
		if plan != c.plan || base != c.base {
			t.Errorf("SplitImageModel(%q) = (%q,%q), want (%q,%q)", c.in, plan, base, c.plan, c.base)
		}
	}
}

func TestImageModelSlug(t *testing.T) {
	cases := map[string]string{
		"gpt-image-2":              "gpt-5-3",
		"codex-gpt-image-2":        "codex-gpt-image-2",
		"plus-codex-gpt-image-2":   "codex-gpt-image-2",
		"":                         "auto",
		"gpt-5":                    "auto",
		"unknown-model":            "auto",
	}
	for in, want := range cases {
		if got := ImageModelSlug(in); got != want {
			t.Errorf("ImageModelSlug(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestIsCodexImageModel(t *testing.T) {
	if !IsCodexImageModel("codex-gpt-image-2") {
		t.Error("codex-gpt-image-2 应为 codex 模型")
	}
	if IsCodexImageModel("gpt-image-2") {
		t.Error("gpt-image-2 非 codex 模型")
	}
}

// ---- payload 字段对齐（1:1 对比 Python 版构建结果）----

// TestPreparePayloadFields 校验 prepare payload 的静态字段与嵌套结构。
// 动态字段（uuid）单独校验非空。
func TestPreparePayloadFields(t *testing.T) {
	p := PrepareImagePayload("一只猫", "gpt-image-2")

	// 静态字段（对齐 Python:1159-1177）
	for key, want := range map[string]any{
		"action":                "next",
		"fork_from_shared_post": false,
		"model":                 "gpt-5-3", // slug 映射生效
		"client_prepare_state":  "success",
		"timezone_offset_min":   -480,
		"timezone":              "Asia/Shanghai",
		"supports_buffering":    true,
	} {
		if got := p[key]; got != want {
			t.Errorf("prepare.%s = %v, want %v", key, got, want)
		}
	}
	if enc, _ := p["supported_encodings"].([]string); len(enc) != 1 || enc[0] != "v1" {
		t.Errorf("prepare.supported_encodings = %v", p["supported_encodings"])
	}
	if hints, _ := p["system_hints"].([]string); len(hints) != 1 || hints[0] != "picture_v2" {
		t.Errorf("prepare.system_hints = %v", p["system_hints"])
	}
	if mode := p["conversation_mode"].(map[string]any); mode["kind"] != "primary_assistant" {
		t.Errorf("prepare.conversation_mode = %v", mode)
	}
	if cci := p["client_contextual_info"].(map[string]any); cci["app_name"] != "chatgpt.com" {
		t.Errorf("prepare.client_contextual_info = %v", cci)
	}

	// 动态字段：uuid 非空
	if pmid, _ := p["parent_message_id"].(string); pmid == "" {
		t.Error("prepare.parent_message_id 为空")
	}
	// partial_query 结构
	pq := p["partial_query"].(map[string]any)
	if pq["author"].(map[string]any)["role"] != "user" {
		t.Error("prepare.partial_query.author.role != user")
	}
	content := pq["content"].(map[string]any)
	if content["content_type"] != "text" {
		t.Error("prepare.partial_query.content.content_type != text")
	}
	if parts := content["parts"].([]string); len(parts) != 1 || parts[0] != "一只猫" {
		t.Errorf("prepare.partial_query.content.parts = %v", parts)
	}
}

// TestStartPayloadTextOnly 纯文生图（无参考图）payload。
func TestStartPayloadTextOnly(t *testing.T) {
	p := StartImagePayload("赛博朋克猫", "gpt-image-2", nil)

	if p["action"] != "next" || p["model"] != "gpt-5-3" || p["client_prepare_state"] != "sent" {
		t.Errorf("start 基础字段错误: %v", p)
	}
	if p["enable_message_followups"] != true || p["supports_buffering"] != true {
		t.Error("start 布尔字段错误")
	}
	if p["paragen_cot_summary_display_override"] != "allow" || p["force_parallel_switch"] != "auto" {
		t.Error("start 覆盖字段错误")
	}

	msgs := p["messages"].([]any)
	if len(msgs) != 1 {
		t.Fatalf("messages 数量 = %d", len(msgs))
	}
	msg := msgs[0].(map[string]any)
	if msg["author"].(map[string]any)["role"] != "user" {
		t.Error("message.author.role != user")
	}
	// 无参考图：content 为纯文本
	content := msg["content"].(map[string]any)
	if content["content_type"] != "text" {
		t.Errorf("无参考图时 content_type = %v, want text", content["content_type"])
	}
	if parts := content["parts"].([]string); len(parts) != 1 || parts[0] != "赛博朋克猫" {
		t.Errorf("parts = %v", parts)
	}
	// metadata 无 attachments 键（对齐 Python：仅 references 时添加）
	meta := msg["metadata"].(map[string]any)
	if _, ok := meta["attachments"]; ok {
		t.Error("无参考图时不应有 attachments")
	}
	if hints := meta["system_hints"].([]string); len(hints) != 1 || hints[0] != "picture_v2" {
		t.Errorf("metadata.system_hints = %v", hints)
	}
	// client_contextual_info 全字段
	cci := p["client_contextual_info"].(map[string]any)
	for _, k := range []string{"is_dark_mode", "time_since_loaded", "page_height", "page_width", "pixel_ratio", "screen_height", "screen_width", "app_name"} {
		if _, ok := cci[k]; !ok {
			t.Errorf("client_contextual_info 缺字段 %s", k)
		}
	}
	if cci["app_name"] != "chatgpt.com" || cci["time_since_loaded"] != 1200 || cci["pixel_ratio"] != 1.2 {
		t.Errorf("client_contextual_info 值错误: %v", cci)
	}
}

// TestStartPayloadWithReferences 带参考图（图生图/编辑）payload。
func TestStartPayloadWithReferences(t *testing.T) {
	refs := []ImageReference{
		{FileID: "file-111", FileName: "image_1.png", FileSize: 12345, MimeType: "image/png", Width: 1024, Height: 768},
		{FileID: "file-222", FileName: "image_2.png", FileSize: 999, MimeType: "image/png", Width: 512, Height: 512},
	}
	p := StartImagePayload("改成夜景", "gpt-image-2", refs)

	msg := p["messages"].([]any)[0].(map[string]any)
	content := msg["content"].(map[string]any)
	if content["content_type"] != "multimodal_text" {
		t.Errorf("有参考图时 content_type = %v, want multimodal_text", content["content_type"])
	}
	parts := content["parts"].([]any)
	if len(parts) != 3 { // 2 指针 + 1 prompt
		t.Fatalf("parts 数量 = %d, want 3", len(parts))
	}
	// 指针在前、prompt 在后（对齐 Python 顺序）
	first := parts[0].(map[string]any)
	if first["content_type"] != "image_asset_pointer" || first["asset_pointer"] != "file-service://file-111" {
		t.Errorf("parts[0] = %v", first)
	}
	if first["width"] != 1024 || first["height"] != 768 || first["size_bytes"] != 12345 {
		t.Errorf("指针尺寸字段错误: %v", first)
	}
	if parts[2] != "改成夜景" {
		t.Errorf("parts[2] = %v, want prompt", parts[2])
	}
	// metadata.attachments
	meta := msg["metadata"].(map[string]any)
	atts := meta["attachments"].([]any)
	if len(atts) != 2 {
		t.Fatalf("attachments = %d", len(atts))
	}
	att := atts[1].(map[string]any)
	if att["id"] != "file-222" || att["mimeType"] != "image/png" || att["name"] != "image_2.png" || att["size"] != 999 {
		t.Errorf("attachments[1] = %v", att)
	}
}

// TestPayloadJSONSerializable payload 必须可 JSON 序列化（tls-client 请求体）。
func TestPayloadJSONSerializable(t *testing.T) {
	for _, raw := range [][]byte{
		PreparePayloadJSON("p", "gpt-image-2"),
		StartPayloadJSON("p", "gpt-image-2", nil),
		StartPayloadJSON("p", "gpt-image-2", []ImageReference{{FileID: "f", FileName: "n", FileSize: 1, MimeType: "image/png", Width: 1, Height: 1}}),
	} {
		var v any
		if err := json.Unmarshal(raw, &v); err != nil {
			t.Fatalf("payload 不可序列化: %v\n%s", err, raw)
		}
	}
}

// ---- 请求头 ----

// TestRequestHeaders 校验 target path/route + Bearer。
func TestRequestHeaders(t *testing.T) {
	b := &Backend{
		BaseURL:           "https://chatgpt.com",
		AccessToken:       "tok123",
		clientVersion:     DefaultClientVersion,
		clientBuildNumber: DefaultClientBuildNumber,
		fp:                DefaultFingerprint(),
	}
	h := b.RequestHeaders("/backend-api/f/conversation", map[string]string{"Content-Type": "application/json"})

	if h.Get("Authorization") != "Bearer tok123" {
		t.Errorf("Authorization = %q", h.Get("Authorization"))
	}
	if h.Get("X-OpenAI-Target-Path") != "/backend-api/f/conversation" || h.Get("X-OpenAI-Target-Route") != "/backend-api/f/conversation" {
		t.Errorf("target path/route 错误: %q / %q", h.Get("X-OpenAI-Target-Path"), h.Get("X-OpenAI-Target-Route"))
	}
	if h.Get("OAI-Client-Version") != DefaultClientVersion {
		t.Errorf("OAI-Client-Version = %q", h.Get("OAI-Client-Version"))
	}
	if h.Get("Origin") != "https://chatgpt.com" || h.Get("Referer") != "https://chatgpt.com/" {
		t.Errorf("Origin/Referer 错误")
	}
	if !strings.Contains(h.Get("User-Agent"), "Edg/143") {
		t.Errorf("User-Agent = %q", h.Get("User-Agent"))
	}
}

// TestImageHeaders 校验图片链路专用头（sentinel token/conduit/trace）。
func TestImageHeaders(t *testing.T) {
	b := &Backend{BaseURL: "https://chatgpt.com", AccessToken: "t",
		clientVersion: DefaultClientVersion, clientBuildNumber: DefaultClientBuildNumber,
		fp: DefaultFingerprint()}

	// 非 SSE：无 trace id
	req := &ChatRequirements{Token: "sentinel-tok", ProofToken: "proof-tok"}
	h := b.ImageHeaders("/backend-api/f/conversation", req, "conduit-tok", "*/*")
	if h.Get("OpenAI-Sentinel-Chat-Requirements-Token") != "sentinel-tok" {
		t.Error("sentinel token 头缺失")
	}
	if h.Get("OpenAI-Sentinel-Proof-Token") != "proof-tok" {
		t.Error("proof token 头缺失")
	}
	if h.Get("X-Conduit-Token") != "conduit-tok" {
		t.Error("conduit token 头缺失")
	}
	if h.Get("X-Oai-Turn-Trace-Id") != "" {
		t.Error("非 SSE 不应有 trace id")
	}

	// SSE：有 trace id；空 proof_token 不带头
	h2 := b.ImageHeaders("/x", &ChatRequirements{Token: "t"}, "", "text/event-stream")
	if h2.Get("X-Oai-Turn-Trace-Id") == "" {
		t.Error("SSE 请求应有 X-Oai-Turn-Trace-Id")
	}
	if _, ok := h2["Openai-Sentinel-Proof-Token"]; ok {
		t.Error("空 proof_token 不应带头")
	}
}

// TestFingerprintMerge 账号指纹覆盖语义（空值忽略）。
func TestFingerprintMerge(t *testing.T) {
	base := DefaultFingerprint()
	merged := base.Merge(map[string]string{
		"user-agent":     "CustomUA/1.0",
		"impersonate":    "edge101",
		"oai-device-id":  "", // 空值不覆盖
	})
	if merged.UserAgent != "CustomUA/1.0" || merged.Impersonate != "edge101" {
		t.Errorf("覆盖失败: %+v", merged)
	}
	if merged.OaiDeviceID != base.OaiDeviceID {
		t.Error("空值不应覆盖")
	}
	// 默认值完整性
	if merged.SecChUaMobile != "?0" || merged.SecChUaPlatform != `"Windows"` {
		t.Errorf("未覆盖字段应保持默认: %+v", merged)
	}
}
