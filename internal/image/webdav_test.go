package image

import (
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

// mockWebDAV 内存 WebDAV 服务器：MKCOL/PUT/GET/DELETE，校验 basic auth。
type mockWebDAV struct {
	mu     sync.Mutex
	files  map[string][]byte
	dirs   map[string]bool
	user   string
	pass   string
	authOK *bool
}

func newMockWebDAV(user, pass string) (*mockWebDAV, *httptest.Server) {
	m := &mockWebDAV{files: map[string][]byte{}, dirs: map[string]bool{}, user: user, pass: pass}
	var authSeen bool
	m.authOK = &authSeen
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		u, p, ok := r.BasicAuth()
		if !ok || u != user || p != pass {
			w.WriteHeader(401)
			return
		}
		*m.authOK = true
		m.mu.Lock()
		defer m.mu.Unlock()
		switch r.Method {
		case "MKCOL":
			if m.dirs[r.URL.Path] {
				w.WriteHeader(405) // 已存在（对齐 Python 容忍）
				return
			}
			m.dirs[r.URL.Path] = true
			w.WriteHeader(201)
		case "PUT":
			b, _ := io.ReadAll(r.Body)
			m.files[r.URL.Path] = b
			w.WriteHeader(201)
		case "GET":
			if b, ok := m.files[r.URL.Path]; ok {
				w.WriteHeader(200)
				w.Write(b)
				return
			}
			w.WriteHeader(404)
		case "DELETE":
			if _, ok := m.files[r.URL.Path]; ok {
				delete(m.files, r.URL.Path)
				w.WriteHeader(204)
				return
			}
			w.WriteHeader(404)
		default:
			w.WriteHeader(405)
		}
	}))
	return m, srv
}

// TestWebDAVRoundtrip P1.5 验收：put/get/delete 全链路 + basic auth + quote。
func TestWebDAVRoundtrip(t *testing.T) {
	m, srv := newMockWebDAV("u", "p")
	defer srv.Close()
	c := NewWebDAVClient(srv.URL, "u", "p", "root sub")
	data := []byte("PNGDATA\x89PNG")
	u, err := c.Put("2026/01/01/img 1.png", data, "image/png")
	if err != nil {
		t.Fatal(err)
	}
	// 逐段 quote：空格 → %20，root 参与拼接
	if !strings.Contains(u, "root%20sub/2026/01/01/img%201.png") {
		t.Fatalf("url not quoted: %s", u)
	}
	got, err := c.Get("2026/01/01/img 1.png")
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != string(data) {
		t.Fatal("roundtrip data mismatch")
	}
	deleted, err := c.Delete("2026/01/01/img 1.png")
	if err != nil || !deleted {
		t.Fatalf("delete=%v err=%v", deleted, err)
	}
	// 404 删除返回 false
	deleted, err = c.Delete("2026/01/01/img 1.png")
	if err != nil || deleted {
		t.Fatalf("second delete=%v err=%v", deleted, err)
	}
	if !*m.authOK {
		t.Fatal("basic auth never seen")
	}
}

// TestWebDAVTest P1.5：连通性自检 + 坏 URL。
func TestWebDAVTest(t *testing.T) {
	_, srv := newMockWebDAV("u", "p")
	defer srv.Close()
	c := NewWebDAVClient(srv.URL, "u", "p", "")
	if r := c.Test(); !r.OK {
		t.Fatalf("self test failed: %+v", r)
	}
	bad := NewWebDAVClient("", "", "", "")
	if r := bad.Test(); r.OK || !strings.Contains(r.Error, "required") {
		t.Fatalf("empty url test=%+v", r)
	}
}

// TestWebDAVStorageModes P1.5：both 模式本地同步 + 纯远端。
func TestWebDAVStorageModes(t *testing.T) {
	_, srv := newMockWebDAV("u", "p")
	defer srv.Close()
	dir := t.TempDir()
	s := NewWebDAVStorage(srv.URL, "u", "p", "", dir)
	if _, err := s.Save("a/b.png", []byte("DATA")); err != nil {
		t.Fatal(err)
	}
	// 本地同步副本
	if _, err := s.local.Load("a/b.png"); err != nil {
		t.Fatalf("local mirror missing: %v", err)
	}
	// 从本地读（断服务端也能读）
	if b, err := s.Load("a/b.png"); err != nil || string(b) != "DATA" {
		t.Fatalf("load=%q err=%v", b, err)
	}
	if err := s.Delete("a/b.png"); err != nil {
		t.Fatal(err)
	}
	// 纯远端模式
	s2 := NewWebDAVStorage(srv.URL, "u", "p", "", "")
	if _, err := s2.Save("x.png", []byte("X")); err != nil {
		t.Fatal(err)
	}
	if b, err := s2.Load("x.png"); err != nil || string(b) != "X" {
		t.Fatalf("remote load=%q err=%v", b, err)
	}
}

// TestSafeRel P1.5：上跳剥离（对齐 _safe_relative_path）。
func TestSafeRel(t *testing.T) {
	cases := map[string]string{
		"a/b.png":         "a/b.png",
		"../x.png":        "x.png",
		"a/../../x.png":   "x.png",
		"/abs/path.png":   "abs/path.png",
		"a\\b.png":        "a/b.png",
		"":                "",
		"a/./b.png":       "a/b.png",
	}
	for in, want := range cases {
		if got := safeRel(in); got != want {
			t.Fatalf("safeRel(%q)=%q want %q", in, got, want)
		}
	}
}

// TestLocalStorageTraversal P1.5：越权路径被 sanitize（.. 剥离）后写目录内，无逃逸。
// 对齐 Python _safe_relative_path + _safe_image_path 策略（净化而非报错）。
func TestLocalStorageTraversal(t *testing.T) {
	dir := t.TempDir()
	s := NewLocal(dir)
	path, err := s.Save("../../escape.png", []byte("x"))
	if err != nil {
		t.Fatal(err)
	}
	// 落点必须在 dir 内
	absDir, _ := filepath.Abs(dir)
	absPath, _ := filepath.Abs(path)
	if !strings.HasPrefix(absPath, absDir) {
		t.Fatalf("escaped: %s not under %s", absPath, absDir)
	}
	// dir 外无逃逸文件
	if _, err := os.Stat(filepath.Join(dir, "..", "escape.png")); err == nil {
		t.Fatal("escape file created outside dir")
	}
	// 读同样 sanitize 命中同一文件
	if b, err := s.Load("../../escape.png"); err != nil || string(b) != "x" {
		t.Fatalf("sanitized load failed: %q %v", b, err)
	}
}
