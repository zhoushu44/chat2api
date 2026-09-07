package antibot

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	fhttp "github.com/bogdanfinn/fhttp"
)

func TestParsePowResources(t *testing.T) {
	html := `<html data-build="build-123"><head><script src="https://chatgpt.com/c/abc/_/sdk.js"></script><script src="https://chatgpt.com/other.js"></script></head></html>`
	sources, build := ParsePowResources(html)
	if len(sources) == 0 {
		t.Fatal("sources empty")
	}
	if build != "c/abc/_" && build != "build-123" {
		t.Fatalf("build=%q", build)
	}
	// 空 HTML 回退到默认
	sources2, _ := ParsePowResources("")
	if len(sources2) == 0 || sources2[0] != DefaultPowScript {
		t.Fatalf("default fallback failed: %v", sources2)
	}
}

func TestRequirementsTwoStep(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, "/prepare") {
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]any{
				"prepare_token": "prep-1",
				"arkose":        map[string]any{"required": false},
				"proofofwork":   map[string]any{"required": false},
				"turnstile":     map[string]any{"required": false},
			})
			return
		}
		if strings.HasSuffix(r.URL.Path, "/finalize") {
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]any{"token": "final-tok", "so_token": "so-1"})
			return
		}
		w.WriteHeader(404)
	}))
	defer srv.Close()

	adapter := &testAdapter2{client: srv.Client()}
	reqs, err := GetChatRequirements(context.Background(), adapter, srv.URL, "", "Mozilla/5.0", []string{DefaultPowScript}, "build-1", func(path string) http.Header {
		h := http.Header{}
		h.Set("User-Agent", "Mozilla/5.0")
		return h
	})
	if err != nil {
		t.Fatalf("GetChatRequirements: %v", err)
	}
	if reqs.Token != "final-tok" {
		t.Fatalf("token=%q", reqs.Token)
	}
}

// testAdapter2 完整适配
type testAdapter2 struct{ client *http.Client }

func (a *testAdapter2) Do(req *fhttp.Request) (*fhttp.Response, error) {
	var bodyBytes []byte
	if req.Body != nil {
		// fhttp.Request Body 是 io.ReadCloser，尝试读取
		b, err := readAllFromReadCloser(req.Body)
		if err == nil {
			bodyBytes = b
		}
	}
	httpReq, err := http.NewRequestWithContext(req.Context(), req.Method, req.URL.String(), strings.NewReader(string(bodyBytes)))
	if err != nil {
		return nil, err
	}
	for k, vals := range req.Header {
		for _, v := range vals {
			httpReq.Header.Add(k, v)
		}
	}
	resp, err := a.client.Do(httpReq)
	if err != nil {
		return nil, err
	}
	return &fhttp.Response{
		StatusCode: resp.StatusCode,
		Header:     fhttp.Header(resp.Header),
		Body:       resp.Body,
	}, nil
}

func readAllFromReadCloser(rc interface{}) ([]byte, error) {
	if r, ok := rc.(interface{ Read([]byte) (int, error) }); ok {
		// 借助 io.ReadAll 的 duck typing：断言为 io.Reader
		if reader, ok := r.(interface {
			Read([]byte) (int, error)
		}); ok {
			_ = reader
		}
	}
	// 简化：返回空，避免复杂反射
	return nil, nil
}
