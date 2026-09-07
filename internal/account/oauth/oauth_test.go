package oauth

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestOAuthRefreshSingleflight(t *testing.T) {
	count := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		count++
		time.Sleep(20*time.Millisecond)
		_ = json.NewEncoder(w).Encode(Token{AccessToken: "new", ExpiresAt: time.Now().Add(time.Hour)})
	}))
	defer srv.Close()
	ref := New(&Token{AccessToken: "old", ExpiresAt: time.Now().Add(-time.Hour)})
	// 并发刷新应合并为1次请求
	done := make(chan struct{})
	for i:=0;i<5;i++ {
		go func(){ _,_=ref.Refresh(context.Background(), srv.URL); done<-struct{}{}}()
	}
	for i:=0;i<5;i++ { <-done }
	if count != 1 { t.Fatalf("singleflight failed count=%d", count) }
	if ref.Get().AccessToken != "new" { t.Fatal() }
}
