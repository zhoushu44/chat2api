package backend

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"sync"
	"time"

	fhttp "github.com/bogdanfinn/fhttp"
	"golang.org/x/sync/errgroup"
)

const (
	downloadTimeout = 120 * time.Second
	maxConcurrency  = 4
)

// DownloadImageBytes 下载单张图片为内存字节（流式 io.Copy，避免一次性大分配峰值）。
func (b *Backend) DownloadImageBytes(ctx context.Context, imageURL string) ([]byte, error) {
	data, _, err := b.downloadToBytes(ctx, imageURL)
	return data, err
}

// DownloadImages 并发下载多张图片（每 worker 4 并发），返回与 urls 一一对应的 bytes 切片。
func (b *Backend) DownloadImages(ctx context.Context, urls []string) ([][]byte, error) {
	if len(urls) == 0 {
		return nil, nil
	}
	results := make([][]byte, len(urls))
	// 限流信号量
	sem := make(chan struct{}, maxConcurrency)
	g, ctx := errgroup.WithContext(ctx)
	for i, u := range urls {
		i, u := i, u
		g.Go(func() error {
			select {
			case sem <- struct{}{}:
			case <-ctx.Done():
				return ctx.Err()
			}
			defer func() { <-sem }()
			data, _, err := b.downloadToBytes(ctx, u)
			if err != nil {
				return fmt.Errorf("download %s: %w", u, err)
			}
			results[i] = data
			return nil
		})
	}
	if err := g.Wait(); err != nil {
		return nil, err
	}
	return results, nil
}

// SaveImages 落盘到 data/images/YYYYMMDD/，流式 io.Copy，返回文件路径与 bytes（可选）。
func (b *Backend) SaveImages(ctx context.Context, urls []string, baseDir string) ([]string, error) {
	if baseDir == "" {
		baseDir = "data/images"
	}
	dateDir := time.Now().Format("20060102")
	dir := filepath.Join(baseDir, dateDir)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return nil, err
	}
	paths := make([]string, len(urls))
	var mu sync.Mutex
	sem := make(chan struct{}, maxConcurrency)
	g, ctx := errgroup.WithContext(ctx)
	for i, u := range urls {
		i, u := i, u
		g.Go(func() error {
			select {
			case sem <- struct{}{}:
			case <-ctx.Done():
				return ctx.Err()
			}
			defer func() { <-sem }()
			path, err := b.downloadToFile(ctx, u, dir, i)
			if err != nil {
				return err
			}
			mu.Lock()
			paths[i] = path
			mu.Unlock()
			return nil
		})
	}
	if err := g.Wait(); err != nil {
		return nil, err
	}
	return paths, nil
}

var bufPool = sync.Pool{New: func() any { b := make([]byte, 32*1024); return &b }}

func (b *Backend) downloadToBytes(ctx context.Context, imageURL string) ([]byte, string, error) {
	headers := b.downloadHeaders(imageURL)
	reqCtx, cancel := context.WithTimeout(ctx, downloadTimeout)
	defer cancel()
	req, err := fhttp.NewRequestWithContext(reqCtx, fhttp.MethodGet, imageURL, nil)
	if err != nil {
		return nil, "", fmt.Errorf("build download request: %w", err)
	}
	req.Header = fhttp.Header(headers)
	resp, err := b.http.Do(req)
	if err != nil {
		return nil, "", fmt.Errorf("download request failed: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		bts, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return nil, "", ensureOK(resp.StatusCode, resp.Header.Get("Retry-After"), bts, "image_download", downloadCredentialScope(imageURL, b.BaseURL))
	}
	// 零拷贝池化：复用 32KB buffer，避免 bytes.Buffer Grow 预分配峰值
	bufPtr := bufPool.Get().(*[]byte)
	defer bufPool.Put(bufPtr)
	tmpBuf := bytes.NewBuffer(nil)
	// 使用池化 slice 作为 CopyBuffer
	if _, err := io.CopyBuffer(tmpBuf, resp.Body, *bufPtr); err != nil {
		return nil, "", fmt.Errorf("read image body: %w", err)
	}
	if tmpBuf.Len() == 0 {
		return nil, "", fmt.Errorf("image download returned an empty response")
	}
	ctype := resp.Header.Get("Content-Type")
	// 拷贝出独立 bytes，避免复用污染
	out := make([]byte, tmpBuf.Len())
	copy(out, tmpBuf.Bytes())
	return out, ctype, nil
}

func (b *Backend) downloadToFile(ctx context.Context, imageURL, dir string, index int) (string, error) {
	headers := b.downloadHeaders(imageURL)
	reqCtx, cancel := context.WithTimeout(ctx, downloadTimeout)
	defer cancel()
	req, err := fhttp.NewRequestWithContext(reqCtx, fhttp.MethodGet, imageURL, nil)
	if err != nil {
		return "", fmt.Errorf("build download request: %w", err)
	}
	req.Header = fhttp.Header(headers)
	resp, err := b.http.Do(req)
	if err != nil {
		return "", fmt.Errorf("download request failed: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		bts, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return "", ensureOK(resp.StatusCode, resp.Header.Get("Retry-After"), bts, "image_download", downloadCredentialScope(imageURL, b.BaseURL))
	}
	ext := ".png"
	if ct := resp.Header.Get("Content-Type"); ct != "" {
		if stringsContains(ct, "jpeg") || stringsContains(ct, "jpg") {
			ext = ".jpg"
		} else if stringsContains(ct, "webp") {
			ext = ".webp"
		}
	}
	filename := fmt.Sprintf("%s_%d%s", time.Now().Format("150405"), index, ext)
	path := filepath.Join(dir, filename)
	f, err := os.Create(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	bufPtr := bufPool.Get().(*[]byte)
	defer bufPool.Put(bufPtr)
	if _, err := io.CopyBuffer(f, resp.Body, *bufPtr); err != nil {
		_ = os.Remove(path)
		return "", fmt.Errorf("save image: %w", err)
	}
	return path, nil
}

func (b *Backend) downloadHeaders(imageURL string) http.Header {
	parsed, err := url.Parse(imageURL)
	sameOrigin := false
	if err == nil && parsed.Host != "" {
		baseParsed, err2 := url.Parse(b.BaseURL)
		if err2 == nil && stringsEqualFold(parsed.Host, baseParsed.Host) {
			sameOrigin = true
		}
	} else if err == nil && parsed.Host == "" {
		sameOrigin = true
	}
	if sameOrigin {
		// 同源走账号鉴权
		path := "/"
		if parsed != nil && parsed.Path != "" {
			path = parsed.Path
		}
		return b.RequestHeaders(path, map[string]string{"Accept": "image/*,*/*"})
	}
	// 签名资源无需鉴权
	return http.Header{
		"Accept":          []string{"image/*,*/*"},
		"Accept-Language": []string{"en-US,en;q=0.8"},
		"User-Agent":      []string{b.fp.UserAgent},
	}
}

func downloadCredentialScope(imageURL, baseURL string) string {
	parsed, err := url.Parse(imageURL)
	if err != nil || parsed.Host == "" {
		return "account"
	}
	baseParsed, err := url.Parse(baseURL)
	if err == nil && stringsEqualFold(parsed.Host, baseParsed.Host) {
		return "account"
	}
	return "signed_asset"
}

func stringsContains(s, substr string) bool {
	return len(s) >= len(substr) && (func() bool {
		for i := 0; i <= len(s)-len(substr); i++ {
			if s[i:i+len(substr)] == substr {
				return true
			}
		}
		return false
	})()
}
func stringsEqualFold(a, b string) bool {
	if len(a) != len(b) {
		// 仍需大小写不敏感比较
	}
	aa := []byte(a)
	bb := []byte(b)
	if len(aa) != len(bb) {
		return false
	}
	for i := range aa {
		ca := aa[i]
		cb := bb[i]
		if ca >= 'A' && ca <= 'Z' {
			ca += 'a' - 'A'
		}
		if cb >= 'A' && cb <= 'Z' {
			cb += 'a' - 'A'
		}
		if ca != cb {
			return false
		}
	}
	return true
}
