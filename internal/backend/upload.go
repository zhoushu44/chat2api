package backend

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"image"
	_ "image/gif"  // 注册 GIF 解码器（image.DecodeConfig 按注册格式探测）
	_ "image/jpeg" // 注册 JPEG 解码器
	_ "image/png"  // 注册 PNG 解码器
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	fhttp "github.com/bogdanfinn/fhttp"
)

// 常量对齐（Python services/openai_backend_api.py:1202-1259 / utils/helper.py:145）。
const (
	// uploadDefaultFileName 文件名缺省值（对等 _upload_image(file_name="image.png")）。
	uploadDefaultFileName = "image.png"
	// upstreamBodyLogLimit 错误消息中响应体截断长度（对等 _UPSTREAM_BODY_LOG_LIMIT=500）。
	upstreamBodyLogLimit = 500
	// 三步流各自超时（对等 Python session.post/put 的 timeout 参数：60/120/60 秒）。
	uploadCreateTimeout  = 60 * time.Second
	uploadPutBlobTimeout = 120 * time.Second
	uploadConfirmTimeout = 60 * time.Second
)

// imageMIMEByFormat 图片格式名 → MIME（对等 PIL Image.MIME 查表，缺省 image/png）。
var imageMIMEByFormat = map[string]string{
	"png":  "image/png",
	"jpeg": "image/jpeg",
	"gif":  "image/gif",
}

// UpstreamHTTPError 上游 HTTP 非 2xx 错误（对等 utils/helper.py:148-183）。
//
// 携带结构化字段（status_code/body/retry_after/credential_scope），
// 调用方可按状态码分支处理，不必对错误字符串做匹配；
// Body 保留完整内容（JSON 反序列化结果或原文），格式化消息时才截断。
type UpstreamHTTPError struct {
	Context         string `json:"context"`          // 出错上下文（API 路径或 "image_upload"）
	StatusCode      int    `json:"status_code"`      // 上游 HTTP 状态码
	Body            any    `json:"body"`             // 响应体（能解析 JSON 时为 map/数组，否则原文）
	RetryAfter      int    `json:"retry_after"`      // Retry-After 头秒数，纯数字才解析；0 表示未携带
	CredentialScope string `json:"credential_scope"` // "account" / "signed_asset" / "public"
}

// Error 实现 error 接口，消息格式对齐 helper.py:183：
// "{context} failed: status={status_code}, body={body_str}"，body 截断 500 字符。
func (e *UpstreamHTTPError) Error() string {
	var bodyStr string
	switch v := e.Body.(type) {
	case nil:
		bodyStr = ""
	case string:
		bodyStr = v
	default:
		// dict/list 走 json 序列化（对齐 isinstance(body, (dict, list)) 分支）
		if b, err := json.Marshal(v); err == nil {
			bodyStr = string(b)
		} else {
			bodyStr = fmt.Sprintf("%v", v)
		}
	}
	// 按字符截断，避免撕裂多字节 UTF-8（Python 按字符切片，语义一致）
	if runes := []rune(bodyStr); len(runes) > upstreamBodyLogLimit {
		bodyStr = string(runes[:upstreamBodyLogLimit]) + "…[truncated]"
	}
	return fmt.Sprintf("%s failed: status=%d, body=%s", e.Context, e.StatusCode, bodyStr)
}

// ensureOK 校验上游响应为 2xx，非 2xx 时返回 *UpstreamHTTPError
// （对等 utils/helper.py:186-211）。
//
// 参数：
//   - statusCode：上游响应状态码
//   - retryAfterHeader：Retry-After 原始头值（可为空；仅纯数字时解析）
//   - body：已读入内存的响应体字节（能解析 JSON 则存解析结果）
//   - errContext：出错上下文（API 路径 / "image_upload"，对齐 Python 参数名 context）
//   - credentialScope：错误凭据范围，非法值回退 "account"（对齐 helper.py:169-173）
func ensureOK(statusCode int, retryAfterHeader string, body []byte, errContext, credentialScope string) error {
	if statusCode >= 200 && statusCode < 300 {
		return nil
	}
	// body 优先尝试 JSON 解析，失败保留原文（对齐 ensure_ok 的 try/except）
	parsedBody := any(string(body))
	var asJSON any
	if len(bytes.TrimSpace(body)) > 0 && json.Unmarshal(body, &asJSON) == nil {
		parsedBody = asJSON
	}
	// Retry-After 仅纯数字时解析（对齐 helper.py:201-204 的 isdigit 判定）
	retryAfter := 0
	if s := strings.TrimSpace(retryAfterHeader); s != "" && isAllDigits(s) {
		if n, err := strconv.Atoi(s); err == nil {
			retryAfter = n
		}
	}
	switch credentialScope {
	case "account", "signed_asset", "public":
	default:
		credentialScope = "account"
	}
	return &UpstreamHTTPError{
		Context:         errContext,
		StatusCode:      statusCode,
		Body:            parsedBody,
		RetryAfter:      retryAfter,
		CredentialScope: credentialScope,
	}
}

func isAllDigits(s string) bool {
	for _, r := range s {
		if r < '0' || r > '9' {
			return false
		}
	}
	return len(s) > 0
}

// DecodeImageBase64 把 base64 图片字符串或本地路径解码成二进制
// （对等 Python _decode_image_base64:1187-1200，判定条件 1:1）。
//
// 支持三种输入：
//  1. 本地文件路径（短于 512 字符、非 data: 前缀、不含换行、文件存在时直接读盘）
//  2. data URI（data:image/xxx;base64,... → 取逗号后部分）
//  3. 纯 base64 字符串
func DecodeImageBase64(image string) ([]byte, error) {
	// 路径启发式判定（对齐 Python 1189-1195 的四条件）
	if isLocalFilePathCandidate(image) {
		if data, err := os.ReadFile(expandHome(image)); err == nil {
			return data, nil
		}
		// 文件不存在/不可读时落回 base64 解码（Python 同语义：条件不满足即走 b64decode）
	}
	// data URI 取逗号后的负载（对齐 Python 1199 的 split(",", 1)）
	payload := image
	if strings.HasPrefix(image, "data:") {
		if idx := strings.IndexByte(image, ','); idx >= 0 {
			payload = image[idx+1:]
		}
	}
	// Python base64.b64decode（validate=False）会忽略字母表外字符；
	// Go 严格模式对应做法：剥离空白字符后按标准字母表解码
	cleaned := stripBase64Whitespace(payload)
	data, err := base64.StdEncoding.DecodeString(cleaned)
	if err != nil {
		return nil, fmt.Errorf("decode image base64: %w", err)
	}
	return data, nil
}

// isLocalFilePathCandidate 输入是否可能是本地文件路径（对齐 Python 1189-1195）：
// 非空、长度 < 512、非 data: 前缀、不含 \n 与 \r。
func isLocalFilePathCandidate(image string) bool {
	return image != "" &&
		len(image) < 512 &&
		!strings.HasPrefix(image, "data:") &&
		!strings.Contains(image, "\n") &&
		!strings.Contains(image, "\r")
}

// expandHome 展开 ~/ 与 ~\ 前缀（对等 os.path.expanduser 的常用子集）。
func expandHome(path string) string {
	if path == "~" {
		if home, err := os.UserHomeDir(); err == nil {
			return home
		}
		return path
	}
	if strings.HasPrefix(path, "~/") || strings.HasPrefix(path, `~\`) {
		if home, err := os.UserHomeDir(); err == nil {
			return filepath.Join(home, path[2:])
		}
	}
	return path
}

// stripBase64Whitespace 剥离 base64 中夹带的空白字符
// （对齐 Python b64decode validate=False 忽略非字母表字符的宽容语义）。
func stripBase64Whitespace(s string) string {
	if !strings.ContainsAny(s, " \t\r\n") {
		return s
	}
	var b strings.Builder
	b.Grow(len(s))
	for i := 0; i < len(s); i++ {
		switch s[i] {
		case ' ', '\t', '\r', '\n':
		default:
			b.WriteByte(s[i])
		}
	}
	return b.String()
}

// probeImage 探测图片宽高与 MIME（对等 Python 1215-1217：
// Image.open → image.size + Image.MIME.get(format, "image/png")）。
//
// 解析发生在第一步请求之前——width/height 直接进入第一步 body（对齐源码顺序）。
// 无法识别的图片字节返回错误（对等 PIL Image.open 抛 UnidentifiedImageError）。
func probeImage(data []byte) (width, height int, mimeType string, err error) {
	cfg, format, err := image.DecodeConfig(bytes.NewReader(data))
	if err != nil {
		return 0, 0, "", fmt.Errorf("identify image: %w", err)
	}
	mimeType = imageMIMEByFormat[format]
	if mimeType == "" {
		mimeType = "image/png" // 对齐 Image.MIME.get(..., "image/png") 缺省
	}
	return cfg.Width, cfg.Height, mimeType, nil
}

// UploadImage 上传一张 base64/路径图片，返回底层文件元数据
// （对等 Python _upload_image:1202-1259 三步流 1:1）。
//
// 三步：
//  1. POST /backend-api/files —— 创建上传（file_id + upload_url）
//  2. PUT upload_url —— Azure Blob 直传原始图片字节（SAS URL 自带鉴权）
//  3. POST /backend-api/files/{file_id}/uploaded —— 确认上传完成
//
// fileName 为空时缺省 "image.png"；当 image 是存在的本地文件路径时，
// fileName 会被覆盖为路径的文件名（对齐 Python 1205-1214）。
func (b *Backend) UploadImage(ctx context.Context, image, fileName string) (*ImageReference, error) {
	if fileName == "" {
		fileName = uploadDefaultFileName
	}
	// 第零步：解码 + 文件名推断（对齐 Python 1204-1214）
	data, err := DecodeImageBase64(image)
	if err != nil {
		return nil, err
	}
	if isLocalFilePathCandidate(image) {
		if info, statErr := os.Stat(expandHome(image)); statErr == nil && !info.IsDir() {
			fileName = filepath.Base(expandHome(image))
		}
	}
	// 尺寸/MIME 探测先于第一步请求（对齐 Python 1215-1217）
	width, height, mimeType, err := probeImage(data)
	if err != nil {
		return nil, err
	}

	// 第一步：创建上传（对齐 Python 1218-1226）
	fileID, uploadURL, err := b.createFileUpload(ctx, fileName, len(data), width, height)
	if err != nil {
		return nil, err
	}
	// 第二步：Azure Blob 直传（对齐 Python 1228-1243）
	if err := b.putAssetBlob(ctx, uploadURL, mimeType, data); err != nil {
		return nil, err
	}
	// 第三步：确认上传完成（对齐 Python 1244-1251）
	if err := b.confirmFileUploaded(ctx, fileID); err != nil {
		return nil, err
	}
	// 返回元数据（对齐 Python 1252-1259 的 dict 字段）
	return &ImageReference{
		FileID:   fileID,
		FileName: fileName,
		FileSize: len(data),
		MimeType: mimeType,
		Width:    width,
		Height:   height,
	}, nil
}

// createFileUpload 第一步：POST /backend-api/files 创建上传任务，
// 返回 file_id 与 upload_url（对齐 Python 1218-1227）。
func (b *Backend) createFileUpload(ctx context.Context, fileName string, fileSize, width, height int) (string, string, error) {
	const path = "/backend-api/files"
	// body 字段 1:1 对齐 Python 1222-1223：
	// file_name / file_size / use_case / width / height（无 total_bytes、无 mime_type）
	payload := map[string]any{
		"file_name": fileName,
		"file_size": fileSize,
		"use_case":  "multimodal",
		"width":     width,
		"height":    height,
	}
	headers := b.RequestHeaders(path, map[string]string{
		"Content-Type": "application/json",
		"Accept":       "application/json",
	})
	reqCtx, cancel := context.WithTimeout(ctx, uploadCreateTimeout)
	defer cancel()
	resp, body, err := b.doUploadRequest(reqCtx, fhttp.MethodPost, b.BaseURL+path, headers, mustJSON(payload))
	if err != nil {
		return "", "", err
	}
	if err := ensureOK(resp.StatusCode, resp.Header.Get("Retry-After"), body, path, "account"); err != nil {
		return "", "", err
	}
	// 解析 upload_meta（对齐 Python response.json()；缺字段时报错对齐 KeyError）
	var meta struct {
		FileID    string `json:"file_id"`
		UploadURL string `json:"upload_url"`
	}
	if err := json.Unmarshal(body, &meta); err != nil {
		return "", "", fmt.Errorf("parse %s response: %w", path, err)
	}
	if meta.UploadURL == "" {
		return "", "", fmt.Errorf("%s response missing upload_url", path)
	}
	if meta.FileID == "" {
		return "", "", fmt.Errorf("%s response missing file_id", path)
	}
	return meta.FileID, meta.UploadURL, nil
}

// putAssetBlob 第二步：PUT upload_url 直传原始图片字节到 Azure Blob
// （对齐 Python 1228-1243）。
//
// 头部语义：Python 的 requests 会把 session.headers 与显式 dict 合并
// （显式键优先），因此这里同样基于 SessionHeaders 覆盖 8 个显式头；
// 该请求不携带 Authorization（SAS URL 自带鉴权），对齐源码。
func (b *Backend) putAssetBlob(ctx context.Context, uploadURL, mimeType string, data []byte) error {
	headers := b.SessionHeaders()
	headers.Set("Content-Type", mimeType)
	headers.Set("X-Ms-Blob-Type", "BlockBlob")
	headers.Set("X-Ms-Version", "2020-04-08")
	headers.Set("Origin", b.BaseURL)
	headers.Set("Referer", b.BaseURL+"/")
	headers.Set("User-Agent", b.fp.UserAgent)
	headers.Set("Accept", "application/json, text/plain, */*")
	headers.Set("Accept-Language", "en-US,en;q=0.8")

	reqCtx, cancel := context.WithTimeout(ctx, uploadPutBlobTimeout)
	defer cancel()
	resp, body, err := b.doUploadRequest(reqCtx, fhttp.MethodPut, uploadURL, headers, data)
	if err != nil {
		return err
	}
	// 错误凭据范围 signed_asset（对齐 Python 1243 的 credential_scope="signed_asset"）
	return ensureOK(resp.StatusCode, resp.Header.Get("Retry-After"), body, "image_upload", "signed_asset")
}

// confirmFileUploaded 第三步：POST /backend-api/files/{file_id}/uploaded
// 确认上传完成（对齐 Python 1244-1251，body 固定 "{}"）。
func (b *Backend) confirmFileUploaded(ctx context.Context, fileID string) error {
	path := "/backend-api/files/" + fileID + "/uploaded"
	headers := b.RequestHeaders(path, map[string]string{
		"Content-Type": "application/json",
		"Accept":       "application/json",
	})
	reqCtx, cancel := context.WithTimeout(ctx, uploadConfirmTimeout)
	defer cancel()
	resp, body, err := b.doUploadRequest(reqCtx, fhttp.MethodPost, b.BaseURL+path, headers, []byte("{}"))
	if err != nil {
		return err
	}
	return ensureOK(resp.StatusCode, resp.Header.Get("Retry-After"), body, path, "account")
}

// doUploadRequest 发送上传三步流的一次 HTTP 请求并把响应体完整读入内存。
// 返回的 resp.Body 已关闭，body 为已读出的字节（供 ensureOK 与 JSON 解析复用）。
// 非传输层错误（状态码非 2xx）由调用方经 ensureOK 判定。
func (b *Backend) doUploadRequest(ctx context.Context, method, url string, headers http.Header, body []byte) (*fhttp.Response, []byte, error) {
	var reader io.Reader
	if body != nil {
		reader = bytes.NewReader(body)
	}
	req, err := fhttp.NewRequestWithContext(ctx, method, url, reader)
	if err != nil {
		return nil, nil, fmt.Errorf("%s %s build request: %w", method, url, err)
	}
	// net/http.Header 与 fhttp.Header 底层类型一致（map[string][]string），直接转换
	req.Header = fhttp.Header(headers)
	resp, err := b.http.Do(req)
	if err != nil {
		return nil, nil, fmt.Errorf("%s %s request failed: %w", method, url, err)
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, nil, fmt.Errorf("%s %s read response: %w", method, url, err)
	}
	return resp, data, nil
}

// 接口守卫：UpstreamHTTPError 必须满足 error（编译期自检，与 mockupstream.go 风格一致）
var _ error = (*UpstreamHTTPError)(nil)
