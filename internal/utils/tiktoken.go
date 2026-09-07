package utils

import (
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"

	tiktoken "github.com/pkoukk/tiktoken-go"
)

// 真实 BPE 计数（P2.8）：对等 tiktoken.encoding_for_model，失败回退 o200k_base。
// 相对旧 len/4 近似，英文误差从 ~30% 降至 0（与 Python 同一 BPE 词表）。
//
// 注意 tiktoken-go 首次从网络下载 BPE 文件（http.Get 无超时）：
// getEncodingCached 用 10s 超时守卫 + 60s 失败缓存兜底，离线时降级 len/4 不阻塞。

var (
	encCache     sync.Map // name -> *tiktoken.Tiktoken
	encFailCache sync.Map // name -> time.Time（失败退避）
)

// SetBPECacheDir 设置 BPE 文件缓存目录（默认系统临时目录；生产建议指向 dataDir 持久化）。
func SetBPECacheDir(dir string) {
	if dir == "" {
		return
	}
	_ = os.MkdirAll(dir, 0755)
	_ = os.Setenv("TIKTOKEN_CACHE_DIR", dir)
}

func bpeCacheDir(dataDir string) {
	if dataDir == "" {
		return
	}
	SetBPECacheDir(filepath.Join(dataDir, "tiktoken-cache"))
}

func getEncodingCached(name string) (*tiktoken.Tiktoken, bool) {
	if e, ok := encCache.Load(name); ok {
		if enc, ok := e.(*tiktoken.Tiktoken); ok && enc != nil {
			return enc, true
		}
	}
	if v, ok := encFailCache.Load(name); ok {
		if ts, ok := v.(time.Time); ok && time.Since(ts) < time.Minute {
			return nil, false
		}
	}
	type res struct {
		e   *tiktoken.Tiktoken
		err error
	}
	ch := make(chan res, 1)
	go func() {
		e, err := tiktoken.GetEncoding(name)
		ch <- res{e, err}
	}()
	select {
	case r := <-ch:
		if r.err != nil || r.e == nil {
			encFailCache.Store(name, time.Now())
			return nil, false
		}
		encCache.Store(name, r.e)
		return r.e, true
	case <-time.After(10 * time.Second):
		encFailCache.Store(name, time.Now())
		return nil, false
	}
}

// CountTokensForModel 文本 token 数（指定模型）。
func CountTokensForModel(text, model string) int {
	// 已知模型直解；未知回退 o200k_base（对等 Python）；全程走超时守卫
	if enc, ok := encodingForModelCached(model); ok {
		return len(enc.Encode(text, nil, nil))
	}
	if enc, ok := getEncodingCached("o200k_base"); ok {
		return len(enc.Encode(text, nil, nil))
	}
	return len(text)/4 + 1
}

// encodingForModelCached 模型→编码（超时守卫；失败 60s 退避）。
func encodingForModelCached(model string) (*tiktoken.Tiktoken, bool) {
	key := "model:" + model
	if e, ok := encCache.Load(key); ok {
		if enc, ok := e.(*tiktoken.Tiktoken); ok && enc != nil {
			return enc, true
		}
	}
	if v, ok := encFailCache.Load(key); ok {
		if ts, ok := v.(time.Time); ok && time.Since(ts) < time.Minute {
			return nil, false
		}
	}
	type res struct {
		e   *tiktoken.Tiktoken
		err error
	}
	ch := make(chan res, 1)
	go func() {
		e, err := tiktoken.EncodingForModel(model)
		ch <- res{e, err}
	}()
	select {
	case r := <-ch:
		if r.err != nil || r.e == nil {
			encFailCache.Store(key, time.Now())
			return nil, false
		}
		encCache.Store(key, r.e)
		return r.e, true
	case <-time.After(10 * time.Second):
		encFailCache.Store(key, time.Now())
		return nil, false
	}
}

// CountTokens 文本 token 数（默认 o200k_base，对等旧语义但真实 BPE）。
func CountTokens(text string) int {
	return CountTokensForModel(text, "gpt-4o")
}

// CountImageTokens 保留旧签名（宽高估算 → 新 patch 模型，默认 auto）。
func CountImageTokens(width, height int) int {
	return CountImageInputTokens(width, height, "", "auto")
}

var sizeRe = regexp.MustCompile(`(\d{2,5})\D+(\d{2,5})`)

// ParseImageSize 解析尺寸（对等 parse_image_size；"1024x1024"/"1024,1024" 等）。
func ParseImageSize(size string) (int, int) {
	m := sizeRe.FindStringSubmatch(size)
	if m == nil {
		return 1024, 1024
	}
	w, err1 := strconv.Atoi(m[1])
	h, err2 := strconv.Atoi(m[2])
	if err1 != nil || err2 != nil || w <= 0 || h <= 0 {
		return 1024, 1024
	}
	return w, h
}

// ImageSizeFromBytes 图片字节 → 宽高（对等 image_size_from_bytes；stdlib DecodeConfig）。
func ImageSizeFromBytes(data []byte) (int, int, bool) {
	w, h, err := imageDecodeConfig(data)
	if err != nil || w <= 0 || h <= 0 {
		return 0, 0, false
	}
	return w, h, true
}

// TokenUsage usage 块（对等 token_usage）。
func TokenUsage(inputText, inputImage, outputText, outputImage int) map[string]any {
	max0 := func(v int) int {
		if v < 0 {
			return 0
		}
		return v
	}
	inText, inImage := max0(inputText), max0(inputImage)
	outText, outImage := max0(outputText), max0(outputImage)
	in, out := inText+inImage, outText+outImage
	return map[string]any{
		"input_tokens":  in,
		"output_tokens": out,
		"total_tokens":  in + out,
		"input_tokens_details": map[string]any{
			"text_tokens": inText, "image_tokens": inImage, "cached_tokens": 0,
		},
		"output_tokens_details": map[string]any{
			"text_tokens": outText, "image_tokens": outImage, "reasoning_tokens": 0,
		},
	}
}

// ImageUsage 对等 image_usage。
func ImageUsage(inputText, inputImage, output int) map[string]any {
	return TokenUsage(inputText, inputImage, 0, output)
}

// ChatUsageFromImageUsage 对等 chat_usage_from_image_usage。
func ChatUsageFromImageUsage(usage map[string]any) map[string]any {
	get := func(m map[string]any, k string) int {
		if m == nil {
			return 0
		}
		switch v := m[k].(type) {
		case int:
			return v
		case float64:
			return int(v)
		default:
			return 0
		}
	}
	in, out := get(usage, "input_tokens"), get(usage, "output_tokens")
	inD, _ := usage["input_tokens_details"].(map[string]any)
	outD, _ := usage["output_tokens_details"].(map[string]any)
	return map[string]any{
		"prompt_tokens":     in,
		"completion_tokens": out,
		"total_tokens":      in + out,
		"prompt_tokens_details": map[string]any{
			"text_tokens": get(inD, "text_tokens"), "image_tokens": get(inD, "image_tokens"), "cached_tokens": get(inD, "cached_tokens"),
		},
		"completion_tokens_details": map[string]any{
			"text_tokens": get(outD, "text_tokens"), "image_tokens": get(outD, "image_tokens"), "reasoning_tokens": get(outD, "reasoning_tokens"),
		},
	}
}

var _ = strings.TrimSpace
