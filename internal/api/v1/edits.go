package v1

import (
	"context"
	"fmt"
	"io"
	"log"
	"net/http"
	"strings"
	"time"

	"chatgpt2api/internal/backend/failure"
	"chatgpt2api/internal/protocol"

	"github.com/gin-gonic/gin"
)

// HandleEditsWith 图片编辑真实链路（P0.2）：/v1/images/edits → orchestrator（带参考图）。
// 支持 multipart（image/image[] 字段）与 JSON（image b64 / image_url）两种输入。
func HandleEditsWith(c *gin.Context, orch *protocol.Orchestrator) {
	if orch == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": gin.H{
			"message": "image edit service unavailable: no account pool configured",
			"type":    "api_error", "code": "service_unavailable",
		}})
		return
	}
	var (
		prompt  string
		model   string
		size    string
		quality string
		images  []string
		n       = 1
	)
	if c.ContentType() == "multipart/form-data" {
		form, err := c.MultipartForm()
		if err == nil && form != nil {
			prompt = c.PostForm("prompt")
			model = c.PostForm("model")
			size = c.PostForm("size")
			quality = c.PostForm("quality")
			files := append(form.File["image"], form.File["image[]"]...)
			for _, fh := range files {
				f, err := fh.Open()
				if err != nil {
					continue
				}
				b := readAll(f)
				f.Close()
				if len(b) > 0 {
					images = append(images, "data:"+fh.Header.Get("Content-Type")+";base64,"+encodeB64(b))
				}
			}
		}
	} else {
		var req struct {
			Prompt   string `json:"prompt"`
			Image    string `json:"image"`
			ImageURL string `json:"image_url"`
			Model    string `json:"model"`
			Size     string `json:"size"`
			Quality  string `json:"quality"`
			N        int    `json:"n"`
		}
		_ = c.ShouldBindJSON(&req)
		prompt = req.Prompt
		model = req.Model
		size = req.Size
		quality = req.Quality
		if req.N > 0 {
			n = req.N
		}
		if req.Image != "" {
			images = append(images, req.Image)
		} else if req.ImageURL != "" {
			images = append(images, req.ImageURL)
		}
	}
	if prompt == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"message": "prompt required", "type": "invalid_request_error", "code": "invalid_image_input"}})
		return
	}
	// http(s) 参考图先下载为 data-URL（对等 Python image_inputs._download_image_url），失败 400。
	resolved := make([]string, 0, len(images))
	for _, im := range images {
		if isHTTPURL(im) {
			dataURI, derr := downloadImageURL(c.Request.Context(), im)
			if derr != nil {
				c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"message": derr.Error(), "type": "invalid_request_error", "code": "invalid_image_input"}})
				return
			}
			resolved = append(resolved, dataURI)
			continue
		}
		resolved = append(resolved, im)
	}
	images = resolved
	if model == "" {
		model = "gpt-image-2"
	}
	if quality == "" {
		quality = "auto"
	}
	if n > 4 {
		n = 4
	}
	res, err := orch.Generate(c.Request.Context(), protocol.GenerateRequest{
		Prompt: protocol.BuildImagePrompt(prompt, size, quality), Model: model, Images: images, N: n,
	})
	if err != nil {
		// 与 generations 同口径：本地输入错误 400，上游错误 502。
		f := failure.Classify(err, 0, err.Error())
		code, httpStatus := f.Code, f.StatusCode
		if httpStatus == 0 {
			code, httpStatus = "upstream_error", http.StatusBadGateway
		}
		c.JSON(httpStatus, gin.H{"error": gin.H{"message": err.Error(), "type": "api_error", "code": code}})
		return
	}
	data := make([]gin.H, 0, n)
	for i := 0; i < n; i++ {
		item := gin.H{}
		if i < len(res.B64) {
			item["b64_json"] = string(res.B64[i])
		} else if i < len(res.URLs) {
			item["url"] = res.URLs[i]
		}
		data = append(data, item)
	}
	if len(data) == 0 {
		c.JSON(http.StatusBadGateway, gin.H{"error": gin.H{"message": "upstream returned no images", "type": "api_error", "code": "upstream_error"}})
		return
	}
	t := res.Timing
	log.Printf("[edits] model=%s n=%d total=%dms pick=%d boot=%d reqs=%d prep=%d sse=%dms initwait=%d pollwait=%d polls=%d resolve=%d dl=%d enc=%d",
		model, n, t.TotalMs, t.AccountPickMs, t.BootstrapMs, t.RequirementsMs, t.PrepareMs,
		t.SSEStreamMs, t.InitialWaitMs, t.PollWaitMs, t.PollCount, t.ResolveMs, t.DownloadMs, t.EncodeMs)
	c.JSON(http.StatusOK, gin.H{"created": 0, "data": data})
}

// HandleEdits 兼容旧入口（无依赖注入时明确 503，不再返回假图）。
func HandleEdits(c *gin.Context) {
	HandleEditsWith(c, nil)
}

func isHTTPURL(s string) bool {
	return strings.HasPrefix(s, "http://") || strings.HasPrefix(s, "https://")
}

// imageURLFetchLimit 对等 Python 的 50MB 上限。
const imageURLFetchLimit = 50 << 20

var imageURLClient = &http.Client{Timeout: 30 * time.Second}

// downloadImageURL 下载 http(s) 参考图并转为 data-URL（对等 _download_image_url：
// 非 http(s)/拉取失败/非 2xx/超限/空内容/非图片一律返回错误，调用方映射 400）。
func downloadImageURL(ctx context.Context, url string) (string, error) {
	if !isHTTPURL(url) {
		return "", fmt.Errorf("image_url must be an http or https URL")
	}
	reqCtx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(reqCtx, http.MethodGet, url, nil)
	if err != nil {
		return "", fmt.Errorf("image_url fetch failed: %v", err)
	}
	resp, err := imageURLClient.Do(req)
	if err != nil {
		return "", fmt.Errorf("image_url fetch failed: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return "", fmt.Errorf("image_url fetch failed: HTTP %d", resp.StatusCode)
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, imageURLFetchLimit+1))
	if err != nil {
		return "", fmt.Errorf("image_url fetch failed: %v", err)
	}
	if len(body) == 0 {
		return "", fmt.Errorf("image_url returned empty content")
	}
	if len(body) > imageURLFetchLimit {
		return "", fmt.Errorf("image_url exceeds 50MB limit")
	}
	mime := http.DetectContentType(body)
	if !strings.HasPrefix(mime, "image/") {
		return "", fmt.Errorf("image_url must point to an image")
	}
	return "data:" + mime + ";base64," + encodeB64(body), nil
}
