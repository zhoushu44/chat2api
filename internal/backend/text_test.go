package backend

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// mockTextServer 文本对话 mock：requirements + POST /backend-api/conversation 返回文本 SSE。
func mockTextServer(t *testing.T, seenPayload *map[string]any) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.Method == "GET" && r.URL.Path == "/":
			w.Write([]byte(`<html data-build="b1"><script src="/sdk.js"></script></html>`))
		case strings.HasSuffix(r.URL.Path, "/sentinel/chat-requirements/prepare"):
			_ = json.NewEncoder(w).Encode(map[string]any{
				"prepare_token": "prep",
				"arkose":        map[string]any{"required": false},
				"proofofwork":   map[string]any{"required": false},
				"turnstile":     map[string]any{"required": false},
			})
		case strings.HasSuffix(r.URL.Path, "/sentinel/chat-requirements/finalize"):
			_ = json.NewEncoder(w).Encode(map[string]any{"token": "tok", "so_token": "so"})
		case r.URL.Path == "/backend-api/conversation" && r.Method == "POST":
			var body map[string]any
			_ = json.NewDecoder(r.Body).Decode(&body)
			*seenPayload = body
			w.Header().Set("Content-Type", "text/event-stream")
			w.WriteHeader(200)
			flusher, _ := w.(http.Flusher)
			w.Write([]byte("data: {\"conversation_id\":\"c1\",\"message\":{\"author\":{\"role\":\"assistant\"},\"content\":{\"content_type\":\"text\",\"parts\":[\"Hi\"]}}}\n\n"))
			if flusher != nil {
				flusher.Flush()
			}
			time.Sleep(10 * time.Millisecond)
			w.Write([]byte("data: {\"conversation_id\":\"c1\",\"message\":{\"author\":{\"role\":\"assistant\"},\"content\":{\"content_type\":\"text\",\"parts\":[\"Hi there\"]}}}\n\n"))
			if flusher != nil {
				flusher.Flush()
			}
			w.Write([]byte("data: [DONE]\n\n"))
			if flusher != nil {
				flusher.Flush()
			}
		default:
			w.WriteHeader(404)
		}
	}))
}

// TestStartTextConversationPayload P2.1 验收：文本请求体字段对齐 Python _conversation_payload。
func TestStartTextConversationPayload(t *testing.T) {
	var seen map[string]any
	srv := mockTextServer(t, &seen)
	defer srv.Close()
	be := NewBackendWithClient(srv.URL, "test-token", &fhttpAdapter{client: srv.Client()})

	body, err := be.StartTextConversation(context.Background(), []map[string]any{
		{"role": "user", "content": "hello"},
	}, "auto", "", nil)
	if err != nil {
		t.Fatal(err)
	}
	defer body.Close()
	if seen["action"] != "next" {
		t.Fatalf("action=%v", seen["action"])
	}
	if seen["model"] != "auto" {
		t.Fatalf("model=%v", seen["model"])
	}
	for _, key := range []string{"parent_message_id", "conversation_mode", "timezone", "force_use_sse", "websocket_request_id", "client_contextual_info"} {
		if _, ok := seen[key]; !ok {
			t.Fatalf("payload missing %q", key)
		}
	}
	msgs, _ := seen["messages"].([]any)
	if len(msgs) != 1 {
		t.Fatalf("messages=%v", seen["messages"])
	}
	m0, _ := msgs[0].(map[string]any)
	author, _ := m0["author"].(map[string]any)
	if author["role"] != "user" {
		t.Fatalf("author=%v", author)
	}
	// headers：sentinel token 透传
	_ = body
}

// TestStreamTextPayloads P2.1：SSE 文本 payload 迭代 + conversation_id 捕获。
func TestStreamTextPayloads(t *testing.T) {
	var seen map[string]any
	srv := mockTextServer(t, &seen)
	defer srv.Close()
	be := NewBackendWithClient(srv.URL, "test-token", &fhttpAdapter{client: srv.Client()})

	body, err := be.StartTextConversation(context.Background(), []map[string]any{
		{"role": "user", "content": "hello"},
	}, "auto", "", nil)
	if err != nil {
		t.Fatal(err)
	}
	defer body.Close()
	var payloads []string
	convID, err := StreamTextPayloads(context.Background(), body, 5*time.Second, func(p string) {
		payloads = append(payloads, p)
	})
	if err != nil {
		t.Fatal(err)
	}
	if convID != "c1" {
		t.Fatalf("convID=%q", convID)
	}
	if len(payloads) != 3 { // 2 message + [DONE]
		t.Fatalf("payloads=%d", len(payloads))
	}
	b, _ := io.ReadAll(strings.NewReader(strings.Join(payloads, "")))
	_ = b
}

// TestAPIMessagesConversion P2.1：string/list 内容转换。
func TestAPIMessagesConversion(t *testing.T) {
	out, err := APIMessagesToConversationMessages([]map[string]any{
		{"role": "system", "content": "be nice"},
		{"role": "user", "content": []any{
			map[string]any{"type": "text", "text": "look"},
			map[string]any{"type": "image_url", "image_url": map[string]any{"url": "http://x/y.png"}},
		}},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(out) != 2 {
		t.Fatalf("len=%d", len(out))
	}
	m1 := out[1]
	content, _ := m1["content"].(map[string]any)
	parts, _ := content["parts"].([]string)
	if len(parts) != 2 || parts[0] != "look" || !strings.Contains(parts[1], "http://x/y.png") {
		t.Fatalf("image_url not folded: %v", parts)
	}
	// 非法 content 类型报错
	if _, err := APIMessagesToConversationMessages([]map[string]any{{"role": "user", "content": 123}}); err == nil {
		t.Fatal("invalid content should error")
	}
}

// TestChatTarget P2.1：auth/anon 路径区分。
func TestChatTarget(t *testing.T) {
	be := NewBackendWithClient("http://x", "tok", &fhttpAdapter{client: http.DefaultClient})
	if path, _ := be.ChatTarget(); path != "/backend-api/conversation" {
		t.Fatalf("auth path=%s", path)
	}
	be2 := NewBackendWithClient("http://x", "", &fhttpAdapter{client: http.DefaultClient})
	if path, tz := be2.ChatTarget(); path != "/backend-anon/conversation" || tz != "America/Los_Angeles" {
		t.Fatalf("anon target=%s %s", path, tz)
	}
}
