package superres

import (
	"bytes"
	"context"
	"fmt"
	"image"
	"image/color"
	"image/png"
	"math/rand"
	"net/http"
	"os"
	"testing"
	"time"
)

// TestLiveBenchmark 真实尺寸基准（手动跑，需 SUPERRES_LIVE_TEST=1）。
// 用 1024x1024 渐变+噪声图模拟真实生成图的复杂度，测量：
//   - 上传+超分耗时（2x / 4x）
//   - 成品文件大小
//   - 顺序 3 连发的耗时稳定性（无并发退化的初步观察）
func TestLiveBenchmark(t *testing.T) {
	cfg := liveTestConfig(t)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
	defer cancel()

	// 1024x1024 渐变 + 伪随机噪声（PNG 压缩率接近真实照片）
	src := buildComplexImage(t, 1024, 1024)
	srcBytes := pngBytes(t, src)
	t.Logf("source: 1024x1024, %d bytes (%.2f MB)", len(srcBytes), float64(len(srcBytes))/1048576)

	for _, factor := range []int{2, 4} {
		plan := &Plan{SourceSize: "1024x1024", Factor: factor}
		started := time.Now()
		dataURL := "data:image/png;base64," + base64Std(srcBytes)
		got := Enhance(ctx, cfg, plan, dataURL)
		elapsed := time.Since(started)
		if got == dataURL {
			t.Fatalf("factor=%d fell back to original (see log)", factor)
		}
		w, h, sizeMB := probeImage(t, got)
		t.Logf("factor=%d: elapsed=%s result=%dx%d size=%.2fMB url=%s",
			factor, elapsed.Round(time.Millisecond), w, h, sizeMB, shortURL(got))
	}
}

// TestLiveSequential 顺序 3 连发 2x（观察腾讯侧排队/限流表现）。
func TestLiveSequential(t *testing.T) {
	cfg := liveTestConfig(t)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
	defer cancel()

	src := pngBytes(t, buildComplexImage(t, 768, 768))
	plan := &Plan{SourceSize: "768x768", Factor: 2}
	for i := 0; i < 3; i++ {
		started := time.Now()
		dataURL := "data:image/png;base64," + base64Std(src)
		got := Enhance(ctx, cfg, plan, dataURL)
		elapsed := time.Since(started)
		if got == dataURL {
			t.Fatalf("round %d fell back (see log)", i+1)
		}
		w, h, sizeMB := probeImage(t, got)
		t.Logf("round %d: elapsed=%s result=%dx%d size=%.2fMB", i+1, elapsed.Round(time.Millisecond), w, h, sizeMB)
	}
}

// buildComplexImage 生成渐变+噪声测试图（PNG 压缩率接近照片级）。
func buildComplexImage(t *testing.T, w, h int) image.Image {
	t.Helper()
	img := image.NewRGBA(image.Rect(0, 0, w, h))
	rng := rand.New(rand.NewSource(42))
	for y := 0; y < h; y++ {
		for x := 0; x < w; x++ {
			// 对角渐变 + 噪声（让 PNG 不可高效压缩，模拟真实照片体积）
			r := uint8(x*255/w + rng.Intn(30))
			g := uint8(y*255/h + rng.Intn(30))
			b := uint8((x+y)*255/(w+h) + rng.Intn(30))
			img.SetRGBA(x, y, color.RGBA{R: r, G: g, B: b, A: 255})
		}
	}
	return img
}

func pngBytes(t *testing.T, img image.Image) []byte {
	t.Helper()
	var buf bytes.Buffer
	if err := png.Encode(&buf, img); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes()
}

// probeImage HEAD 探测：尺寸（解码首块）+ Content-Length。
func probeImage(t *testing.T, url string) (w, h int, sizeMB float64) {
	t.Helper()
	resp, err := http.Get(url)
	if err != nil {
		t.Fatalf("probe: %v", err)
	}
	defer resp.Body.Close()
	cl := resp.Header.Get("Content-Length")
	var total int64
	fmt.Sscanf(cl, "%d", &total)
	cfgImg, _, err := image.DecodeConfig(resp.Body)
	if err != nil {
		t.Fatalf("decode config: %v", err)
	}
	return cfgImg.Width, cfgImg.Height, float64(total) / 1048576
}

func shortURL(u string) string {
	if len(u) > 90 {
		return u[:90] + "..."
	}
	return u
}

// 确保不引入未用 import（os 仅在 liveTestConfig 用）。
var _ = os.Getenv
