package backend

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
)

// TQ1：新形状 rate_limits 数组 → 剩余额度 = max_limit - used_metric。
func TestParseAccountQuotaRateLimitsArray(t *testing.T) {
	body := []byte(`{"rate_limits":[
		{"feature":"msg_too_long_for_model","used_metric":0.0,"max_limit":100.0},
		{"feature":"image_gen","used_metric":3.0,"max_limit":100.0,"quota_type":"primary","resets_in":1800.0}
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

// TQ2：额度用满 → 0（不是负数）。
func TestParseAccountQuotaExhausted(t *testing.T) {
	body := []byte(`{"rate_limits":[{"feature":"image_gen","used_metric":100.0,"max_limit":100.0}]}`)
	q, _ := parseAccountQuota(body)
	if q.Quota != 0 {
		t.Fatalf("Quota=%d want 0", q.Quota)
	}
}

// TQ3：max_limit=0 → 明确无配额，Quota=0。
func TestParseAccountQuotaZeroLimit(t *testing.T) {
	body := []byte(`{"rate_limits":[{"feature":"image_gen","used_metric":0.0,"max_limit":0.0}]}`)
	q, _ := parseAccountQuota(body)
	if q.Quota != 0 {
		t.Fatalf("Quota=%d want 0", q.Quota)
	}
}

// TQ4：旧形状 image_gen 对象 → 兼容。
func TestParseAccountQuotaLegacyShape(t *testing.T) {
	body := []byte(`{"image_gen":{"used":10,"limit":50}}`)
	q, _ := parseAccountQuota(body)
	if q.Quota != 40 {
		t.Fatalf("Quota=%d want 40", q.Quota)
	}
}

// TQ5：形状不识别 → OK=true + Quota=0（quota_unknown 语义，不阻断）。
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

// TQ6：plan 字段提取（chatgpt_plan_type）。
func TestParseAccountQuotaPlan(t *testing.T) {
	body := []byte(`{"chatgpt_plan_type":"plus","rate_limits":[{"feature":"image_gen","used_metric":0,"max_limit":80}]}`)
	q, _ := parseAccountQuota(body)
	if q.PlanType != "Plus" {
		t.Fatalf("PlanType=%q want Plus", q.PlanType)
	}
}

// TQ7：401 → FetchAccountQuota 报错（token 失效语义，由调用方分类）。
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

// TQ8：正常 200 → Quota 解析成功，路径含 feature=image_gen。
func TestFetchAccountQuotaOK(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/backend-api/rate_limits" {
			t.Errorf("path=%s", r.URL.Path)
		}
		if r.URL.Query().Get("feature") != "image_gen" {
			t.Errorf("feature=%s", r.URL.Query().Get("feature"))
		}
		if r.Header.Get("Authorization") != "Bearer tok" {
			t.Errorf("auth header missing")
		}
		w.Write([]byte(`{"rate_limits":[{"feature":"image_gen","used_metric":2.0,"max_limit":30.0}]}`))
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
