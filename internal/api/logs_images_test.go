package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"

	"chatgpt2api/internal/logsvc"

	"github.com/gin-gonic/gin"
)

func TestLogsReturnsJSON(t *testing.T) {
	gin.SetMode(gin.TestMode)
	svc := logsvc.New(10)
	svc.Add(&logsvc.LoggedCall{ID: "log-1", Prompt: "draw a cat", Model: "gpt-image-2", Status: "success", CreatedAt: time.Now()})
	h := &LogsHandler{Svc: svc}
	_, r := gin.CreateTestContext(httptest.NewRecorder())
	h.Register(r.Group("/api"))
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/api/logs", nil)
	r.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("code=%d", w.Code)
	}
	var body map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
		t.Fatalf("not JSON: %v %s", err, w.Body.String())
	}
	if body["total"].(float64) != 1 {
		t.Fatalf("total=%v", body["total"])
	}
}

func TestImagesListAndStorage(t *testing.T) {
	gin.SetMode(gin.TestMode)
	dir := t.TempDir()
	if err := os.MkdirAll(filepath.Join(dir, "images", "20261029"), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "images", "20261029", "a.png"), []byte("png-data"), 0644); err != nil {
		t.Fatal(err)
	}
	h := &ImagesHandler{DataDir: dir}
	_, r := gin.CreateTestContext(httptest.NewRecorder())
	h.Register(r.Group("/api"))

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/api/images", nil)
	r.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("code=%d", w.Code)
	}
	var list struct {
		Items []map[string]any `json:"items"`
		Total int              `json:"total"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &list); err != nil || list.Total != 1 || len(list.Items) != 1 {
		t.Fatalf("list=%+v err=%v", list, err)
	}
	if list.Items[0]["path"] != "20261029/a.png" {
		t.Fatalf("path=%v", list.Items[0]["path"])
	}

	w = httptest.NewRecorder()
	req, _ = http.NewRequest("GET", "/api/images/storage", nil)
	r.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("storage code=%d", w.Code)
	}
}

func TestImagePathTraversalRejected(t *testing.T) {
	h := &ImagesHandler{DataDir: t.TempDir()}
	if _, err := h.fullPath("../secret.txt"); err == nil {
		t.Fatal("path traversal should be rejected")
	}
	if _, err := h.fullPath("/etc/passwd"); err == nil {
		t.Fatal("absolute path should be rejected")
	}
}
