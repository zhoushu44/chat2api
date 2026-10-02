package superres

import (
	"bytes"
	"image"
	"image/color"
	"image/png"
	"net/http"
	"os"
	"testing"
	"time"
)

// liveTestConfig 从环境变量读取真实凭证（SUPERRES_LIVE_TEST=1 时启用）。
func liveTestConfig(t *testing.T) *Config {
	t.Helper()
	if os.Getenv("SUPERRES_LIVE_TEST") != "1" {
		t.Skip("SUPERRES_LIVE_TEST != 1, skipping live test")
	}
	cfg := &Config{
		Enabled:        true,
		SecretID:       os.Getenv("SUPERRES_SECRET_ID"),
		SecretKey:      os.Getenv("SUPERRES_SECRET_KEY"),
		Bucket:         os.Getenv("SUPERRES_BUCKET"),
		Region:         os.Getenv("SUPERRES_REGION"),
		PublicBaseURL:  os.Getenv("SUPERRES_PUBLIC_BASE_URL"),
		UploadEndpoint: os.Getenv("SUPERRES_UPLOAD_ENDPOINT"),
	}
	if !cfg.Ready() {
		t.Fatal("live test env incomplete")
	}
	return cfg
}

// buildTestPNG 生成 64x64 PNG（base64 内嵌，避免引入 image 依赖）。
// 腾讯超分对输入图有最小尺寸限制（实测 8x8 会报 ImageTooLarge），
// 64x64 满足其宽高要求。生成方式：用标准库画一张纯色图。
func buildTestPNG(t *testing.T) []byte {
	t.Helper()
	const size = 64
	img := image.NewRGBA(image.Rect(0, 0, size, size))
	blue := color.RGBA{R: 0x30, G: 0x70, B: 0xE0, A: 0xFF}
	for y := 0; y < size; y++ {
		for x := 0; x < size; x++ {
			img.Set(x, y, blue)
		}
	}
	var buf bytes.Buffer
	if err := png.Encode(&buf, img); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes()
}

// downloadImageSize 下载成品图并返回实际像素尺寸（验证超分真的放大了）。
func downloadImageSize(t *testing.T, url string) (w, h int) {
	t.Helper()
	client := &http.Client{Timeout: 30 * time.Second}
	resp, err := client.Get(url)
	if err != nil {
		t.Fatalf("download result: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		t.Fatalf("download result: HTTP %d", resp.StatusCode)
	}
	img, _, err := image.Decode(resp.Body)
	if err != nil {
		t.Fatalf("decode result: %v", err)
	}
	b := img.Bounds()
	return b.Dx(), b.Dy()
}
