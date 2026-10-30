package egress

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
)

func TestProxyForDisabledReturnsEmpty(t *testing.T) {
	s := New("http://127.0.0.1:1/x?sid={sid}", "")
	if got := s.ProxyFor("a@b.com"); got != "" {
		t.Fatalf("disabled should return empty, got %q", got)
	}
}

func TestProxyForOrdersByAccountStable(t *testing.T) {
	var calls int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&calls, 1)
		sid := r.URL.Query().Get("sid")
		_ = json.NewEncoder(w).Encode(map[string]any{
			"code": "00000",
			"data": map[string]any{
				"proxies": []map[string]any{
					{"proxy": "socks5://127.0.0.1:10001", "sid": sid, "proxy_whitelist": "socks5://127.0.0.1:11001"},
				},
			},
		})
	}))
	defer srv.Close()

	s := New(srv.URL+"/api/proxies?num=1&type=json&sid={sid}", "k")
	s.SetEnabled(true)

	p1 := s.ProxyFor("userA@x.com")
	if p1 != "socks5://127.0.0.1:10001" {
		t.Fatalf("unexpected proxy %q", p1)
	}
	// 第二次命中缓存，不应再请求上游
	p2 := s.ProxyFor("userA@x.com")
	if p2 != p1 {
		t.Fatalf("cache mismatch %q vs %q", p2, p1)
	}
	if atomic.LoadInt32(&calls) != 1 {
		t.Fatalf("cache should hit once, calls=%d", calls)
	}
	// 不同账号生成不同 sid（粘性出口按账号隔离）
	if SidFor("a@x.com") == SidFor("b@x.com") {
		t.Fatal("different accounts must have different sids")
	}
	if SidFor("a@x.com") != SidFor("a@x.com") {
		t.Fatal("same account must have stable sid")
	}
}

func TestProxyForFallsBackOnError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer srv.Close()
	s := New(srv.URL+"/x?sid={sid}", "")
	s.SetEnabled(true)
	if got := s.ProxyFor("a@b.com"); got != "" {
		t.Fatalf("should fall back to empty on upstream error, got %q", got)
	}
}
