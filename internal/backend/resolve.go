package backend

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"strings"
	"time"

	fhttp "github.com/bogdanfinn/fhttp"
)

// ResolveImageURLs 将 file_ids / sediment_ids 解析为可下载 URL
// 对等 openai_backend_api.py:3078 _resolve_image_urls / 3000 _get_file_download_url
func (b *Backend) ResolveImageURLs(ctx context.Context, conversationID string, fileIDs, sedimentIDs []string) ([]string, error) {
	var urls []string
	for _, fid := range fileIDs {
		u, err := b.getFileDownloadURL(ctx, fid)
		if err != nil {
			return nil, err
		}
		urls = append(urls, u)
	}
	for _, sid := range sedimentIDs {
		u, err := b.getSedimentDownloadURL(ctx, conversationID, sid)
		if err != nil {
			return nil, err
		}
		urls = append(urls, u)
	}
	// 同步透过会话文档兜底（_resolve_image_urls_with_timing 逻辑简化）
	if len(urls) == 0 && conversationID != "" {
		if docURLs, _ := b.resolveViaConversation(ctx, conversationID); len(docURLs) > 0 {
			urls = append(urls, docURLs...)
		}
	}
	return urls, nil
}

func (b *Backend) getFileDownloadURL(ctx context.Context, fileID string) (string, error) {
	// 尝试 backend-api/files/{id}/download
	for _, path := range []string{
		"/backend-api/files/" + fileID + "/download",
		"/backend-api/files/download/" + fileID,
	} {
		if u, _, err := b.getDownloadURLOnce(ctx, path); err == nil && u != "" {
			return u, nil
		}
	}
	return "", fmt.Errorf("resolve file %s: no url", fileID)
}

func (b *Backend) getSedimentDownloadURL(ctx context.Context, conversationID, sedimentID string) (string, error) {
	// sediment 直达 conversation 附件接口（对等 _get_attachment_download_url），一次命中；
	// 失败回落 files 接口（兼容上游统一收口，保持修前可用性）。
	if conversationID != "" {
		path := "/backend-api/conversation/" + conversationID + "/attachment/" + sedimentID + "/download"
		t0 := time.Now()
		u, _, err := b.getDownloadURLOnce(ctx, path)
		log.Printf("[resolve] sediment via=attachment ok=%v ms=%d", err == nil && u != "", time.Since(t0).Milliseconds())
		if err == nil && u != "" {
			return u, nil
		}
	}
	u, err := b.getFileDownloadURL(ctx, sedimentID)
	log.Printf("[resolve] sediment via=files-fallback ok=%v", err == nil && u != "")
	return u, err
}

// getDownloadURLOnce 单次解析下载地址：返回 (url, statusCode, err)，调用方决定回落/重试。
func (b *Backend) getDownloadURLOnce(ctx context.Context, path string) (string, int, error) {
	headers := b.RequestHeaders(path, map[string]string{"Accept": "application/json"})
	reqCtx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	resp, body, err := b.doJSONRequest(reqCtx, fhttp.MethodGet, b.BaseURL+path, headers, nil)
	if err != nil {
		return "", 0, err
	}
	if resp.StatusCode == 404 {
		return "", resp.StatusCode, nil
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return "", resp.StatusCode, fmt.Errorf("resolve %s: status %d", path, resp.StatusCode)
	}
	var out struct {
		URL         string `json:"url"`
		DownloadURL string `json:"download_url"`
	}
	_ = json.Unmarshal(body, &out)
	if out.DownloadURL != "" {
		return out.DownloadURL, resp.StatusCode, nil
	}
	if out.URL != "" {
		return out.URL, resp.StatusCode, nil
	}
	// 普通文本 url
	if s := strings.TrimSpace(string(body)); strings.HasPrefix(s, "http") {
		return s, resp.StatusCode, nil
	}
	return "", resp.StatusCode, fmt.Errorf("resolve %s: empty url", path)
}

func (b *Backend) resolveViaConversation(ctx context.Context, conversationID string) ([]string, error) {
	doc, _, err := b.FetchConversation(ctx, conversationID)
	if err != nil || doc == nil {
		return nil, err
	}
	// doc 本身不含 url，需二次查询；此处返回空由上层下载直连
	_ = doc
	return nil, nil
}
