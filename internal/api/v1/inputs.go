package v1

import (
	"encoding/base64"
	"fmt"
	"io"
	"net/http"
	"strings"
)

// ParseImageInput 对等 api/image_inputs.py
// 支持 multipart/URL/b64 三种输入，统一返回原始字节
func ParseImageInput(r *http.Request) ([]byte, string, error) {
	// 尝试 multipart
	if strings.HasPrefix(r.Header.Get("Content-Type"), "multipart/form-data") {
		if err := r.ParseMultipartForm(32 << 20); err == nil {
			// image / image[] 字段
			for _, key := range []string{"image", "image[]", "file"} {
				if fh, ok := r.MultipartForm.File[key]; ok && len(fh) > 0 {
					f, _ := fh[0].Open()
					b, _ := io.ReadAll(f)
					f.Close()
					return b, fh[0].Filename, nil
				}
			}
			// 字段值 b64
			for _, key := range []string{"image_url", "image_b64"} {
				if v := r.FormValue(key); v != "" {
					return decodeMaybeBase64(v)
				}
			}
		}
	}
	// JSON body 尝试
	var body map[string]any
	// 已在上层 ShouldBindJSON，此处仅处理 image_url 重复字段
	_ = body
	return nil, "", fmt.Errorf("no image input")
}

func decodeMaybeBase64(s string) ([]byte, string, error) {
	if strings.HasPrefix(s, "data:") {
		if idx := strings.Index(s, ","); idx >= 0 {
			s = s[idx+1:]
		}
	}
	// URL 透传
	if strings.HasPrefix(s, "http://") || strings.HasPrefix(s, "https://") {
		return []byte(s), "url", nil
	}
	b, err := base64.StdEncoding.DecodeString(strings.TrimSpace(s))
	if err != nil {
		// 尝试 raw
		b2, err2 := base64.RawStdEncoding.DecodeString(strings.TrimSpace(s))
		if err2 != nil {
			return nil, "", err
		}
		return b2, "b64", nil
	}
	return b, "b64", nil
}
