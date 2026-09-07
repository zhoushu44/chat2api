package backend

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"image"
	"image/png"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

// ---- 测试基建：三步流 mock 上游（httptest）----

const (
	// mockFileID 第一步返回的 file_id。
	mockFileID = "file-upload-001"
	// mockBlobPath 第二步 Azure Blob SAS 路径（upload_url 指向 mock 自身）。
	mockBlobPath = "/upload/blob-sas"
)

// uploadCall 一次到达 mock 服务器的请求快照（供三步流断言）。
type uploadCall struct {
	Method string
	Path   string
	Header http.Header
	Body   []byte
}

// uploadMockServer httptest 版 ChatGPT 上游：实现 /backend-api/files 三步流路由，
// 记录调用序列与顺序，并支持第二步/第三步失败注入。
type uploadMockServer struct {
	srv   *httptest.Server
	mu    sync.Mutex
	calls []uploadCall

	failPutStatus     int    // 第二步 PUT 状态码（0 = 正常 201）
	failConfirmStatus int    // 第三步 POST .../uploaded 状态码（0 = 正常 200）
	confirmRetryAfter string // 第三步失败响应的 Retry-After 头
}

// newUploadMockServer 起一个三步流 mock 服务器（测试结束自动关闭）。
func newUploadMockServer(t *testing.T, failPut, failConfirm int, retryAfter string) *uploadMockServer {
	t.Helper()
	m := &uploadMockServer{
		failPutStatus:     failPut,
		failConfirmStatus: failConfirm,
		confirmRetryAfter: retryAfter,
	}
	m.srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		// 先记录再写响应：客户端读完响应时记录必然已完成
		m.mu.Lock()
		m.calls = append(m.calls, uploadCall{Method: r.Method, Path: r.URL.Path, Header: r.Header.Clone(), Body: body})
		m.mu.Unlock()
		switch {
		case r.Method == http.MethodPost && r.URL.Path == "/backend-api/files":
			// 第一步：返回 file_id + 绝对 upload_url（Azure SAS 形态）
			w.Header().Set("Content-Type", "application/json")
			fmt.Fprintf(w, `{"file_id":%q,"upload_url":%q}`, mockFileID, m.srv.URL+mockBlobPath)
		case r.Method == http.MethodPut && r.URL.Path == mockBlobPath:
			// 第二步：Azure Blob 201 Created
			if m.failPutStatus != 0 {
				w.Header().Set("Content-Type", "application/json")
				w.WriteHeader(m.failPutStatus)
				_, _ = w.Write([]byte(`{"error":"forbidden"}`))
				return
			}
			w.WriteHeader(http.StatusCreated)
		case r.Method == http.MethodPost && r.URL.Path == "/backend-api/files/"+mockFileID+"/uploaded":
			// 第三步：确认上传
			if m.failConfirmStatus != 0 {
				if m.confirmRetryAfter != "" {
					w.Header().Set("Retry-After", m.confirmRetryAfter)
				}
				w.Header().Set("Content-Type", "text/plain") // 非 JSON body：验证原文保留
				w.WriteHeader(m.failConfirmStatus)
				_, _ = w.Write([]byte("upstream exploded"))
				return
			}
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"status":"success"}`))
		default:
			t.Errorf("意外的请求：%s %s", r.Method, r.URL.Path)
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	t.Cleanup(m.srv.Close)
	return m
}

// recorded 返回调用序列快照（浅拷贝，调用结束后不再变化）。
func (m *uploadMockServer) recorded() []uploadCall {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := make([]uploadCall, len(m.calls))
	copy(out, m.calls)
	return out
}

// countPathContains 统计路径包含 sub 的调用次数。
func (m *uploadMockServer) countPathContains(sub string) int {
	n := 0
	for _, c := range m.recorded() {
		if strings.Contains(c.Path, sub) {
			n++
		}
	}
	return n
}

// newUploadTestBackend 指向 mock 服务器的后端客户端（真实 tls-client，走完整 HTTP 链路）。
func newUploadTestBackend(t *testing.T, srvURL string) *Backend {
	t.Helper()
	b, err := NewBackend("test-access-token", nil, "")
	if err != nil {
		t.Fatalf("NewBackend: %v", err)
	}
	b.BaseURL = srvURL
	return b
}

// testPNGBytes 用标准库 image/png 构造最小 PNG 字节（宽高可指定）。
func testPNGBytes(t *testing.T, w, h int) []byte {
	t.Helper()
	var buf bytes.Buffer
	if err := png.Encode(&buf, image.NewRGBA(image.Rect(0, 0, w, h))); err != nil {
		t.Fatalf("png encode: %v", err)
	}
	return buf.Bytes()
}

// ---- 三步流（对齐 Python _upload_image:1202-1259）----

// TestUploadImageSuccess 三步流成功：断言每步的方法/路径/body 字段/关键头，
// 以及宽高在第一步请求之前由 image.DecodeConfig 解析并直接进入第一步 body。
func TestUploadImageSuccess(t *testing.T) {
	pngBytes := testPNGBytes(t, 7, 5) // 7×5 最小 PNG

	t.Run("dataURI 输入 + 缺省文件名", func(t *testing.T) {
		m := newUploadMockServer(t, 0, 0, "")
		b := newUploadTestBackend(t, m.srv.URL)

		dataURI := "data:image/png;base64," + base64.StdEncoding.EncodeToString(pngBytes)
		ref, err := b.UploadImage(context.Background(), dataURI, "")
		if err != nil {
			t.Fatalf("UploadImage: %v", err)
		}

		calls := m.recorded()
		if len(calls) != 3 {
			t.Fatalf("三步流应恰好 3 次请求，实际 %d 次：%+v", len(calls), calls)
		}

		// ---- 第一步：POST /backend-api/files ----
		create := calls[0]
		if create.Method != "POST" || create.Path != "/backend-api/files" {
			t.Errorf("第一步应为 POST /backend-api/files，实际 %s %s", create.Method, create.Path)
		}
		var step1 map[string]any
		if err := json.Unmarshal(create.Body, &step1); err != nil {
			t.Fatalf("第一步 body 非法 JSON: %v", err)
		}
		// 字段 1:1 对齐 Python 1222-1223
		for key, want := range map[string]any{
			"file_name": "image.png", // fileName 为空 → 缺省值（对齐 Python 默认参数）
			"file_size": float64(len(pngBytes)),
			"use_case":  "multimodal",
			"width":     float64(7), // 尺寸先于第一步解析（对齐 Python 1215-1217）
			"height":    float64(5),
		} {
			if got := step1[key]; got != want {
				t.Errorf("第一步 body.%s = %v, want %v", key, got, want)
			}
		}
		// Python 源码第一步 body 无 total_bytes / mime_type——断言确实缺失
		if _, ok := step1["total_bytes"]; ok {
			t.Error("第一步 body 不应含 total_bytes（按源码 1:1）")
		}
		if _, ok := step1["mime_type"]; ok {
			t.Error("第一步 body 不应含 mime_type（按源码 1:1）")
		}
		if got := create.Header.Get("Authorization"); got != "Bearer test-access-token" {
			t.Errorf("第一步 Authorization = %q, want Bearer test-access-token", got)
		}
		if got := create.Header.Get("Content-Type"); got != "application/json" {
			t.Errorf("第一步 Content-Type = %q, want application/json", got)
		}
		if got := create.Header.Get("X-OpenAI-Target-Path"); got != "/backend-api/files" {
			t.Errorf("第一步 X-OpenAI-Target-Path = %q", got)
		}

		// ---- 第二步：PUT upload_url（Azure Blob 直传原始字节）----
		put := calls[1]
		if put.Method != "PUT" || put.Path != mockBlobPath {
			t.Errorf("第二步应为 PUT %s，实际 %s %s", mockBlobPath, put.Method, put.Path)
		}
		for key, want := range map[string]string{
			"Content-Type":    "image/png",
			"X-Ms-Blob-Type":  "BlockBlob",
			"X-Ms-Version":    "2020-04-08",
			"Origin":          m.srv.URL,
			"Referer":         m.srv.URL + "/",
			"User-Agent":      b.fp.UserAgent,
			"Accept":          "application/json, text/plain, */*",
			"Accept-Language": "en-US,en;q=0.8",
		} {
			if got := put.Header.Get(key); got != want {
				t.Errorf("第二步 header %s = %q, want %q", key, got, want)
			}
		}
		if got := put.Header.Get("Authorization"); got != "" {
			t.Errorf("第二步不应携带 Authorization（SAS URL 自带鉴权），实际 %q", got)
		}
		if !bytes.Equal(put.Body, pngBytes) {
			t.Errorf("第二步 body 应为原始图片字节（%d 字节），实际 %d 字节", len(pngBytes), len(put.Body))
		}

		// ---- 第三步：POST /backend-api/files/{file_id}/uploaded ----
		confirm := calls[2]
		wantPath := "/backend-api/files/" + mockFileID + "/uploaded"
		if confirm.Method != "POST" || confirm.Path != wantPath {
			t.Errorf("第三步应为 POST %s，实际 %s %s", wantPath, confirm.Method, confirm.Path)
		}
		if string(confirm.Body) != "{}" {
			t.Errorf("第三步 body = %q, want \"{}\"", string(confirm.Body))
		}
		if got := confirm.Header.Get("Authorization"); got != "Bearer test-access-token" {
			t.Errorf("第三步 Authorization = %q", got)
		}

		// ---- 返回值（对齐 Python 1252-1259 的 dict 字段）----
		want := ImageReference{
			FileID:   mockFileID,
			FileName: "image.png",
			FileSize: len(pngBytes),
			MimeType: "image/png",
			Width:    7,
			Height:   5,
		}
		if *ref != want {
			t.Errorf("UploadImage 返回 %+v, want %+v", *ref, want)
		}
	})

	t.Run("本地路径输入 → 文件名取路径 basename", func(t *testing.T) {
		m := newUploadMockServer(t, 0, 0, "")
		b := newUploadTestBackend(t, m.srv.URL)

		// 路径短于 512、无换行 → 走读盘分支，file_name 被路径名覆盖（对齐 Python 1205-1214）
		path := filepath.Join(t.TempDir(), "cat-photo.png")
		if err := os.WriteFile(path, pngBytes, 0o600); err != nil {
			t.Fatalf("write temp png: %v", err)
		}
		ref, err := b.UploadImage(context.Background(), path, "fallback.png")
		if err != nil {
			t.Fatalf("UploadImage: %v", err)
		}
		if ref.FileName != "cat-photo.png" {
			t.Errorf("FileName = %q, want 路径 basename \"cat-photo.png\"", ref.FileName)
		}
		if ref.Width != 7 || ref.Height != 5 {
			t.Errorf("宽高 = %d×%d, want 7×5", ref.Width, ref.Height)
		}
		// basename 也应进入第一步 body
		calls := m.recorded()
		if len(calls) != 3 {
			t.Fatalf("三步流应恰好 3 次请求，实际 %d 次", len(calls))
		}
		var step1 map[string]any
		if err := json.Unmarshal(calls[0].Body, &step1); err != nil {
			t.Fatalf("第一步 body 非法 JSON: %v", err)
		}
		if got := step1["file_name"]; got != "cat-photo.png" {
			t.Errorf("第一步 body.file_name = %v, want \"cat-photo.png\"", got)
		}
	})
}

// TestUploadImageStep2Forbidden 第二步 PUT 403：断言错误类型/状态码/凭据范围，
// 且不继续第三步（对齐 Python 1243 ensure_ok(..., credential_scope="signed_asset")）。
func TestUploadImageStep2Forbidden(t *testing.T) {
	m := newUploadMockServer(t, http.StatusForbidden, 0, "")
	b := newUploadTestBackend(t, m.srv.URL)
	pngBytes := testPNGBytes(t, 4, 9)

	_, err := b.UploadImage(context.Background(), base64.StdEncoding.EncodeToString(pngBytes), "")
	if err == nil {
		t.Fatal("第二步 403 应返回错误")
	}
	var ue *UpstreamHTTPError
	if !errors.As(err, &ue) {
		t.Fatalf("错误应为 *UpstreamHTTPError，实际 %T: %v", err, err)
	}
	if ue.StatusCode != http.StatusForbidden {
		t.Errorf("StatusCode = %d, want 403", ue.StatusCode)
	}
	if ue.Context != "image_upload" {
		t.Errorf("Context = %q, want \"image_upload\"", ue.Context)
	}
	if ue.CredentialScope != "signed_asset" {
		t.Errorf("CredentialScope = %q, want \"signed_asset\"", ue.CredentialScope)
	}
	// body 能解析 JSON → 存为 map（对齐 ensure_ok 的 response.json() 优先）
	bodyMap, ok := ue.Body.(map[string]any)
	if !ok {
		t.Fatalf("Body 应为 JSON 对象，实际 %T: %v", ue.Body, ue.Body)
	}
	if bodyMap["error"] != "forbidden" {
		t.Errorf("Body[\"error\"] = %v, want \"forbidden\"", bodyMap["error"])
	}
	if msg := ue.Error(); !strings.Contains(msg, "image_upload failed: status=403") {
		t.Errorf("错误消息应含 \"image_upload failed: status=403\"，实际 %q", msg)
	}
	// 不继续第三步
	if got := m.countPathContains("/uploaded"); got != 0 {
		t.Errorf("第二步失败后不应发起第三步，实际发起了 %d 次", got)
	}
	if n := len(m.recorded()); n != 2 {
		t.Errorf("应只发生前两步（2 次请求），实际 %d 次", n)
	}
}

// TestUploadImageStep3ServerError 第三步 500：断言前两步已完成、错误上下文为 API 路径、
// 非 JSON body 保留原文、Retry-After 纯数字解析（对齐 helper.py:199-204）。
func TestUploadImageStep3ServerError(t *testing.T) {
	m := newUploadMockServer(t, 0, http.StatusInternalServerError, "7")
	b := newUploadTestBackend(t, m.srv.URL)
	pngBytes := testPNGBytes(t, 3, 3)

	_, err := b.UploadImage(context.Background(), base64.StdEncoding.EncodeToString(pngBytes), "")
	if err == nil {
		t.Fatal("第三步 500 应返回错误")
	}
	var ue *UpstreamHTTPError
	if !errors.As(err, &ue) {
		t.Fatalf("错误应为 *UpstreamHTTPError，实际 %T: %v", err, err)
	}
	wantContext := "/backend-api/files/" + mockFileID + "/uploaded"
	if ue.Context != wantContext {
		t.Errorf("Context = %q, want %q", ue.Context, wantContext)
	}
	if ue.StatusCode != http.StatusInternalServerError {
		t.Errorf("StatusCode = %d, want 500", ue.StatusCode)
	}
	if ue.CredentialScope != "account" {
		t.Errorf("CredentialScope = %q, want \"account\"（第三步缺省凭据范围）", ue.CredentialScope)
	}
	if ue.Body != "upstream exploded" {
		t.Errorf("Body = %#v, want 原文 \"upstream exploded\"（非 JSON 不解析）", ue.Body)
	}
	if ue.RetryAfter != 7 {
		t.Errorf("RetryAfter = %d, want 7（Retry-After 头纯数字应被解析）", ue.RetryAfter)
	}
	// 前两步已完成（第三步发出后失败）
	if n := len(m.recorded()); n != 3 {
		t.Errorf("三步都应已发起（3 次请求），实际 %d 次", n)
	}
}

// TestUploadImageInvalidImageBytes 非图片字节：尺寸探测在第一步请求之前失败，
// 不发出任何 HTTP 请求（对齐 Python Image.open 先于 session.post）。
func TestUploadImageInvalidImageBytes(t *testing.T) {
	m := newUploadMockServer(t, 0, 0, "")
	b := newUploadTestBackend(t, m.srv.URL)

	garbage := base64.StdEncoding.EncodeToString([]byte("definitely not an image"))
	_, err := b.UploadImage(context.Background(), garbage, "")
	if err == nil {
		t.Fatal("非图片字节应报错（对齐 PIL Image.open 抛 UnidentifiedImageError）")
	}
	if !strings.Contains(err.Error(), "identify image") {
		t.Errorf("错误应来自尺寸探测（identify image），实际 %v", err)
	}
	if n := len(m.recorded()); n != 0 {
		t.Errorf("尺寸探测失败不应发出任何 HTTP 请求，实际 %d 次", n)
	}
}

// ---- base64/路径解码（对齐 Python _decode_image_base64:1187-1200）----

// TestDecodeImageBase64 三种合法输入 + 非法输入报错。
func TestDecodeImageBase64(t *testing.T) {
	pngBytes := testPNGBytes(t, 2, 2)
	raw := []byte("hello world")

	tmpPath := filepath.Join(t.TempDir(), "pixel.png")
	if err := os.WriteFile(tmpPath, pngBytes, 0o600); err != nil {
		t.Fatalf("write temp file: %v", err)
	}

	cases := []struct {
		name  string
		input string
		want  []byte
	}{
		{"纯 base64", base64.StdEncoding.EncodeToString(raw), raw},
		{"带换行的 base64（对齐 Python 宽容解码）", "aGVs\r\nbG8g\r\nd29y\r\nbGQ=", raw},
		{"data URI", "data:image/png;base64," + base64.StdEncoding.EncodeToString(pngBytes), pngBytes},
		{"本地文件路径", tmpPath, pngBytes},
	}
	for _, c := range cases {
		got, err := DecodeImageBase64(c.input)
		if err != nil {
			t.Errorf("%s: DecodeImageBase64 意外报错: %v", c.name, err)
			continue
		}
		if !bytes.Equal(got, c.want) {
			t.Errorf("%s: 解码得 %d 字节, want %d 字节", c.name, len(got), len(c.want))
		}
	}

	// 非法输入必须报错
	for _, bad := range []string{
		"!!!",                   // 非法字母表（路径不存在 → 落回 base64 解码失败）
		"data:image/png;base64", // data 前缀但无逗号 → 整串非合法 b64（对齐 Python 1199 落回原串）
	} {
		if _, err := DecodeImageBase64(bad); err == nil {
			t.Errorf("DecodeImageBase64(%q) 应报错", bad)
		}
	}
}
