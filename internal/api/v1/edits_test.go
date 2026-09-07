package v1

import (
	"context"
	"encoding/base64"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// 1x1 透明 PNG（mock 上游/参考图，避免真实出网）。
const tinyPNGb64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="

func TestDownloadImageURLPNG(t *testing.T) {
	raw, _ := base64.StdEncoding.DecodeString(tinyPNGb64)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "image/png")
		_, _ = w.Write(raw)
	}))
	defer srv.Close()
	got, err := downloadImageURL(context.Background(), srv.URL+"/cat.png")
	if err != nil {
		t.Fatalf("err: %v", err)
	}
	if !strings.HasPrefix(got, "data:image/png;base64,") {
		t.Fatalf("prefix: %.40q", got)
	}
}

func TestDownloadImageURLRejects(t *testing.T) {
	if _, err := downloadImageURL(context.Background(), "ftp://x/y.png"); err == nil {
		t.Fatal("non-http should fail")
	}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, "/404.png") {
			w.WriteHeader(404)
			return
		}
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write([]byte("<html>not an image</html>"))
	}))
	defer srv.Close()
	if _, err := downloadImageURL(context.Background(), srv.URL+"/404.png"); err == nil {
		t.Fatal("404 should fail")
	}
	if _, err := downloadImageURL(context.Background(), srv.URL+"/page"); err == nil {
		t.Fatal("non-image should fail")
	}
}
