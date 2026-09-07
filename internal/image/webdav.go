package image

import (
	"bytes"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// WebDAVClient 真实 WebDAV 客户端（P1.5：对等 image_storage_service.py WebDAVClient）。
// 支持：MKCOL 逐级建目录、PUT/GET/DELETE、basic auth、对齐 Python 的 per-segment quote。
type WebDAVClient struct {
	URL      string // 服务器根，如 https://dav.example.com/remote.php/dav/files/user
	Username string
	Password string
	Root     string // 根下子目录（webdav_root_path）
	client   *http.Client
}

// NewWebDAVClient 创建客户端（默认 30s 超时，对齐 Python）。
func NewWebDAVClient(webdavURL, username, password, root string) *WebDAVClient {
	return &WebDAVClient{
		URL:      strings.TrimRight(strings.TrimSpace(webdavURL), "/"),
		Username: username,
		Password: password,
		Root:     strings.Trim(strings.TrimSpace(root), "/"),
		client:   &http.Client{Timeout: 30 * time.Second},
	}
}

// remoteURL 拼接根+相对路径并逐段 quote（对等 remote_url）。
func (c *WebDAVClient) remoteURL(rel string) string {
	parts := []string{}
	if c.Root != "" {
		parts = append(parts, c.Root)
	}
	if rel = safeRel(rel); rel != "" {
		parts = append(parts, rel)
	}
	var segs []string
	for _, p := range parts {
		for _, seg := range strings.Split(p, "/") {
			if seg != "" {
				segs = append(segs, url.PathEscape(seg))
			}
		}
	}
	if len(segs) == 0 {
		return c.URL
	}
	return c.URL + "/" + strings.Join(segs, "/")
}

// safeRel 相对路径规范化（拒绝 .. 上跳，对齐 _safe_relative_path）。
func safeRel(rel string) string {
	rel = strings.TrimSpace(strings.ReplaceAll(rel, "\\", "/"))
	rel = strings.Trim(rel, "/")
	var out []string
	for _, seg := range strings.Split(rel, "/") {
		switch seg {
		case "", ".":
			continue
		case "..":
			if len(out) > 0 {
				out = out[:len(out)-1]
			}
			continue
		default:
			out = append(out, seg)
		}
	}
	return strings.Join(out, "/")
}

// do 带 basic auth 的请求（对等 _auth_kwargs/_request；MKCOL 405 视为已存在）。
func (c *WebDAVClient) do(method, url string, body []byte, contentType string) (*http.Response, error) {
	var r io.Reader
	if body != nil {
		r = bytes.NewReader(body)
	}
	req, err := http.NewRequest(method, url, r)
	if err != nil {
		return nil, err
	}
	if c.Username != "" || c.Password != "" {
		req.SetBasicAuth(c.Username, c.Password)
	}
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	resp, err := c.client.Do(req)
	if err != nil {
		return nil, err
	}
	return resp, nil
}

// EnsureDirs 逐级 MKCOL（对等 ensure_dirs；201/405 跳过）。
func (c *WebDAVClient) EnsureDirs(rel string) error {
	parent := rel
	if i := strings.LastIndex(parent, "/"); i >= 0 {
		parent = parent[:i]
	} else {
		parent = ""
	}
	parts := []string{}
	if c.Root != "" {
		parts = append(parts, c.Root)
	}
	if parent = safeRel(parent); parent != "" {
		parts = append(parts, parent)
	}
	current := c.URL
	for _, item := range strings.Split(strings.Join(parts, "/"), "/") {
		if item == "" {
			continue
		}
		current += "/" + url.PathEscape(item)
		resp, err := c.do("MKCOL", current, nil, "")
		if err != nil {
			return err
		}
		io.Copy(io.Discard, resp.Body)
		resp.Body.Close()
		if resp.StatusCode == 201 || resp.StatusCode == 405 {
			continue
		}
		if resp.StatusCode >= 400 {
			return fmt.Errorf("webdav MKCOL failed: HTTP %d", resp.StatusCode)
		}
	}
	return nil
}

// Put 上传（对等 put），返回远端 URL。
func (c *WebDAVClient) Put(rel string, payload []byte, contentType string) (string, error) {
	if err := c.EnsureDirs(rel); err != nil {
		return "", err
	}
	if contentType == "" {
		contentType = "image/png"
	}
	u := c.remoteURL(rel)
	resp, err := c.do("PUT", u, payload, contentType)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	io.Copy(io.Discard, resp.Body)
	if resp.StatusCode >= 400 {
		return "", fmt.Errorf("webdav PUT failed: HTTP %d", resp.StatusCode)
	}
	return u, nil
}

// Get 下载（对等 get）。
func (c *WebDAVClient) Get(rel string) ([]byte, error) {
	resp, err := c.do("GET", c.remoteURL(rel), nil, "")
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	b, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("webdav GET failed: HTTP %d", resp.StatusCode)
	}
	return b, nil
}

// Delete 删除（对等 delete；404 视为已删返回 false）。
func (c *WebDAVClient) Delete(rel string) (bool, error) {
	resp, err := c.do("DELETE", c.remoteURL(rel), nil, "")
	if err != nil {
		return false, err
	}
	defer resp.Body.Close()
	io.Copy(io.Discard, resp.Body)
	if resp.StatusCode == 404 {
		return false, nil
	}
	if resp.StatusCode != 200 && resp.StatusCode != 202 && resp.StatusCode != 204 {
		return false, fmt.Errorf("webdav DELETE failed: HTTP %d", resp.StatusCode)
	}
	return true, nil
}

// TestResult 连通性检查结果（对等 test）。
type TestResult struct {
	OK     bool   `json:"ok"`
	Status int    `json:"status"`
	Error  string `json:"error,omitempty"`
}

// Test 写入测试文件再删除验证（对等 test）。
func (c *WebDAVClient) Test() TestResult {
	if c.URL == "" {
		return TestResult{OK: false, Error: "WebDAV URL is required"}
	}
	u, err := url.Parse(c.URL)
	if err != nil || (u.Scheme != "http" && u.Scheme != "https") {
		return TestResult{OK: false, Error: "invalid WebDAV URL"}
	}
	testRel := ".chatgpt2api_webdav_test.txt"
	if _, err := c.Put(testRel, []byte("chatgpt2api webdav test\n"), "text/plain"); err != nil {
		return TestResult{OK: false, Error: err.Error()}
	}
	if _, err := c.Delete(testRel); err != nil {
		return TestResult{OK: false, Error: err.Error()}
	}
	return TestResult{OK: true, Status: 200}
}
