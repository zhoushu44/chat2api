package admin

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"chatgpt2api/internal/protocol"

	"github.com/gin-gonic/gin"
)

// 端到端验证图片管理页：存档器落盘 → gallery List → file 预览 → delete。
func TestGalleryListFromArchiver(t *testing.T) {
	gin.SetMode(gin.TestMode)
	dataDir := t.TempDir()

	// 1. 存档器写两张图（模拟生图成功后落盘，含开关关闭分支）
	arch := &protocol.ImageArchiver{DataDir: dataDir, EnabledFunc: func() bool { return true }}
	rel1 := arch.Archive([]byte("fake-png-bytes-1"), 0)
	rel2 := arch.Archive([]byte("fake-png-bytes-2"), 1)
	if rel1 == "" || rel2 == "" {
		t.Fatalf("archive 应返回相对路径: %q %q", rel1, rel2)
	}
	if arch.Archive(nil, 0) != "" {
		t.Fatal("空数据应跳过存档")
	}
	disabled := &protocol.ImageArchiver{DataDir: dataDir, EnabledFunc: func() bool { return false }}
	if disabled.Archive([]byte("x"), 0) != "" {
		t.Fatal("开关关闭时应跳过存档")
	}

	// 2. gallery List 应识别到这两张图
	h := &GalleryHandler{DataDir: dataDir}
	w := httptest.NewRecorder()
	_, r := gin.CreateTestContext(w)
	g := r.Group("/api")
	h.Register(g)

	w = httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/api/images?limit=10", nil)
	r.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("list code %d: %s", w.Code, w.Body.String())
	}
	var listResp struct {
		Items []struct {
			Path string `json:"path"`
			URL  string `json:"url"`
			Type string `json:"type"`
			Name string `json:"name"`
		} `json:"items"`
		Total     int   `json:"total"`
		TotalSize int64 `json:"total_size"`
		Counts    struct {
			All   int `json:"all"`
			Image int `json:"image"`
		} `json:"counts"`
	}
	if err := json.NewDecoder(w.Body).Decode(&listResp); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if listResp.Total != 2 || listResp.Counts.Image != 2 {
		t.Fatalf("total=%d image=%d, want 2/2（含 1 张开关关闭未落盘的：无）", listResp.Total, listResp.Counts.Image)
	}
	for _, it := range listResp.Items {
		if !strings.HasSuffix(it.Path, ".png") || it.Type != "image" {
			t.Fatalf("item 异常: %+v", it)
		}
	}

	// 3. file 预览：取第一张的 url 拉原图字节
	first := listResp.Items[0]
	w = httptest.NewRecorder()
	req, _ = http.NewRequest("GET", first.URL, nil)
	r.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("file code %d", w.Code)
	}
	if !strings.Contains(w.Body.String(), "fake-png-bytes") {
		t.Fatalf("file 内容不符: %q", w.Body.String())
	}

	// 4. 路径穿越防护
	w = httptest.NewRecorder()
	req, _ = http.NewRequest("GET", "/api/images/file?path=../../etc/passwd", nil)
	r.ServeHTTP(w, req)
	if w.Code != http.StatusForbidden && w.Code != http.StatusNotFound {
		t.Fatalf("穿越应被拒: %d", w.Code)
	}

	// 5. 删除一张后 total 应为 1
	delBody, _ := json.Marshal(map[string]any{"paths": []string{first.Path}})
	w = httptest.NewRecorder()
	req, _ = http.NewRequest("POST", "/api/images/delete", bytes.NewReader(delBody))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("delete code %d", w.Code)
	}
	w = httptest.NewRecorder()
	req, _ = http.NewRequest("GET", "/api/images", nil)
	r.ServeHTTP(w, req)
	_ = json.NewDecoder(w.Body).Decode(&listResp)
	if listResp.Total != 1 {
		t.Fatalf("删除后 total=%d, want 1", listResp.Total)
	}
}

// 验证日期目录契约：存档路径 YYYYMMDD/HHMMSS_N.png 与 gallery 的 dateKey 解析对齐。
func TestGalleryDateDirContract(t *testing.T) {
	gin.SetMode(gin.TestMode)
	dataDir := t.TempDir()
	// 手工造一个旧日期目录（模拟历史遗留），gallery 应能按日期过滤
	old := filepath.Join(dataDir, "images", "20200101")
	if err := os.MkdirAll(old, 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(old, "legacy.png"), []byte("x"), 0644); err != nil {
		t.Fatal(err)
	}
	today := filepath.Join(dataDir, "images", time.Now().Format("20060102"))
	if err := os.MkdirAll(today, 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(today, "today.png"), []byte("y"), 0644); err != nil {
		t.Fatal(err)
	}

	h := &GalleryHandler{DataDir: dataDir}
	w := httptest.NewRecorder()
	_, r := gin.CreateTestContext(w)
	g := r.Group("/api")
	h.Register(g)

	// 不过滤：2 条
	w = httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/api/images", nil)
	r.ServeHTTP(w, req)
	var all struct {
		Total int `json:"total"`
	}
	_ = json.NewDecoder(w.Body).Decode(&all)
	if all.Total != 2 {
		t.Fatalf("all total=%d, want 2", all.Total)
	}

	// 按日期过滤（只看 2020 年）：1 条
	w = httptest.NewRecorder()
	req, _ = http.NewRequest("GET", "/api/images?start_date=2020-01-01&end_date=2020-12-31", nil)
	r.ServeHTTP(w, req)
	var filtered struct {
		Total int `json:"total"`
	}
	_ = json.NewDecoder(w.Body).Decode(&filtered)
	if filtered.Total != 1 {
		t.Fatalf("filtered total=%d, want 1", filtered.Total)
	}
}
