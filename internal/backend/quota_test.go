package backend

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
)

// TQ1：limits_progress 数组命中 image_gen → 剩余额度 = remaining。
func TestParseAccountQuotaLimitsProgress(t *testing.T) {
	body := []byte(`{"limits_progress":[
		{"feature_name":"image_gen","remaining":97,"reset_after":"2026-10-08T00:00:00Z"}
	]}`)
	q, err := parseAccountQuota(body)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	if !q.OK {
		t.Fatal("OK should be true")
	}
	if q.Quota != 97 {
		t.Fatalf("Quota=%d want 97", q.Quota)
	}
}

// TQ2：额度用满（remaining=0）→ 0（不是负数）。
func TestParseAccountQuotaExhausted(t *testing.T) {
	body := []byte(`{"limits_progress":[{"feature_name":"image_gen","remaining":0}]}`)
	q, _ := parseAccountQuota(body)
	if q.Quota != 0 {
		t.Fatalf("Quota=%d want 0", q.Quota)
	}
}

// TQ3：limits_progress 存在但无 image_gen 项 → OK=true + Quota=0（quota_unknown 语义）。
func TestParseAccountQuotaNoImageGenEntry(t *testing.T) {
	body := []byte(`{"limits_progress":[{"feature_name":"gpt4","remaining":10}]}`)
	q, err := parseAccountQuota(body)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	if !q.OK || q.Quota != 0 {
		t.Fatalf("q=%+v want OK=true Quota=0", q)
	}
}

// TQ4：形状不识别 → OK=true + Quota=0（quota_unknown 语义，不阻断）。
func TestParseAccountQuotaUnknownShape(t *testing.T) {
	body := []byte(`{"something_else":true}`)
	q, err := parseAccountQuota(body)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	if !q.OK || q.Quota != 0 {
		t.Fatalf("q=%+v want OK=true Quota=0", q)
	}
}

// TQ5：plan 字段提取（chatgpt_plan_type）。
func TestParseAccountQuotaPlan(t *testing.T) {
	body := []byte(`{"chatgpt_plan_type":"plus","limits_progress":[{"feature_name":"image_gen","remaining":80}]}`)
	q, _ := parseAccountQuota(body)
	if q.PlanType != "Plus" {
		t.Fatalf("PlanType=%q want Plus", q.PlanType)
	}
}

// TQ6：401 → FetchAccountQuota 报错（token 失效语义，由调用方分类）。
func TestFetchAccountQuota401(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(401)
	}))
	defer srv.Close()
	be := NewBackendWithClient(srv.URL, "tok", &fhttpAdapter{client: srv.Client()})
	_, err := be.FetchAccountQuota(context.Background())
	if err == nil {
		t.Fatal("401 should fail")
	}
}

// TQ7：正常 200 → Quota 解析成功，路径/方法/鉴权头正确。
func TestFetchAccountQuotaOK(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			t.Errorf("method=%s want POST", r.Method)
		}
		if r.URL.Path != "/backend-api/conversation/init" {
			t.Errorf("path=%s", r.URL.Path)
		}
		if r.Header.Get("Authorization") != "Bearer tok" {
			t.Errorf("auth header missing")
		}
		if got, _ := io.ReadAll(r.Body); string(got) != string(conversationInitBody) {
			t.Errorf("body=%s", string(got))
		}
		w.Write([]byte(`{"limits_progress":[{"feature_name":"image_gen","remaining":28}]}`))
	}))
	defer srv.Close()
	be := NewBackendWithClient(srv.URL, "tok", &fhttpAdapter{client: srv.Client()})
	q, err := be.FetchAccountQuota(context.Background())
	if err != nil {
		t.Fatalf("fetch: %v", err)
	}
	if q.Quota != 28 || !q.OK {
		t.Fatalf("q=%+v want Quota=28", q)
	}
}
