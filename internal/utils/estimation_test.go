package utils

import (
	"bytes"
	"image"
	"image/color"
	"image/png"
	"strings"
	"testing"
)

// TestPatchTokensExact P2.8：手算对拍（1024×1024, gpt-5.4-mini×1.62, auto）。
// limits=(1536,2048)；scale=1；patches=32²=1024≤1536；ceil(1024×1.62)=1659。
func TestPatchTokensExact(t *testing.T) {
	if got := CountImageInputTokens(1024, 1024, "gpt-4o", "auto"); got != 1659 {
		t.Fatalf("patch 1024 auto=%d want 1659", got)
	}
	// low：ceil(256×1.62)=415
	if got := CountImageInputTokens(1024, 1024, "gpt-4o", "low"); got != 415 {
		t.Fatalf("patch low=%d want 415", got)
	}
	// 模型参数被忽略（对等 Python 固定 IMAGE_INPUT_TOKEN_MODEL）：
	// 100×100 → patches=ceil(100/32)²=16 → ceil(16×1.62)=26
	if got := CountImageInputTokens(100, 100, "some-unknown-model", "auto"); got != 26 {
		t.Fatalf("100x100=%d want 26", got)
	}
	if got := CountImageInputTokens(0, 100, "x", "auto"); got != 0 {
		t.Fatalf("zero size=%d", got)
	}
}

// TestTileTokensExact P2.8：手算对拍（1024×1024, gpt-4o 默认费率 85/170）。
// scale=1；short=1024→768/1024 缩放→768²；tiles=2²=4；85+4×170=765。
func TestTileTokensExact(t *testing.T) {
	if got := CountImageTileTokens(1024, 1024, "gpt-4o", "auto"); got != 765 {
		t.Fatalf("tile 1024 auto=%d want 765", got)
	}
	if got := CountImageTileTokens(1024, 1024, "gpt-4o", "low"); got != 85 {
		t.Fatalf("tile low=%d want 85", got)
	}
	// gpt-5 费率 70/140：同尺寸 → 70+4×140=630
	if got := CountImageTileTokens(1024, 1024, "gpt-5", "auto"); got != 630 {
		t.Fatalf("gpt-5 tile=%d want 630", got)
	}
}

// TestGeneratedTokensExact P2.8：1024² patches=1024；auto ceil(1056)=1056；low 272；high 4160。
func TestGeneratedTokensExact(t *testing.T) {
	if got := CountGeneratedImageTokens(1024, 1024, "auto"); got != 1056 {
		t.Fatalf("gen auto=%d want 1056", got)
	}
	if got := CountGeneratedImageTokens(1024, 1024, "low"); got != 272 {
		t.Fatalf("gen low=%d want 272", got)
	}
	if got := CountGeneratedImageTokens(1024, 1024, "high"); got != 4160 {
		t.Fatalf("gen high=%d want 4160", got)
	}
	if got := CountImageOutputTokens("1024x1024", "auto", 2); got != 2112 {
		t.Fatalf("output x2=%d want 2112", got)
	}
}

// TestRealBPE P2.8：真实分词（非 len/4 近似）。
func TestRealBPE(t *testing.T) {
	// "hello world" BPE=2（cl100k/o200k 均为 2）；len/4+1=3 → 证明走了真 BPE
	if got := CountTokens("hello world"); got != 2 {
		t.Fatalf("bpe=%d want 2", got)
	}
	// 未知模型回退 o200k 不崩
	if got := CountTokensForModel("hello world", "no-such-model-xyz"); got != 2 {
		t.Fatalf("fallback=%d want 2", got)
	}
	// 长文本：BPE 显著少于 len/4（英文平均 ~4 字符/token 且含空格合并）
	long := strings.Repeat("The quick brown fox jumps over the lazy dog. ", 20)
	bpe := CountTokens(long)
	approx := len(long)/4 + 1
	if bpe >= approx {
		t.Fatalf("bpe=%d approx=%d, expected bpe < approx", bpe, approx)
	}
	if bpe <= 0 {
		t.Fatalf("bpe=%d", bpe)
	}
}

// TestTokenUsageShape P2.8：usage 块口径。
func TestTokenUsageShape(t *testing.T) {
	u := TokenUsage(10, 5, 7, 3)
	if u["input_tokens"] != 15 || u["output_tokens"] != 10 || u["total_tokens"] != 25 {
		t.Fatalf("usage=%v", u)
	}
	inD, _ := u["input_tokens_details"].(map[string]any)
	if inD["text_tokens"] != 10 || inD["image_tokens"] != 5 || inD["cached_tokens"] != 0 {
		t.Fatalf("input details=%v", inD)
	}
	cu := ChatUsageFromImageUsage(ImageUsage(10, 5, 7))
	if cu["prompt_tokens"] != 15 || cu["completion_tokens"] != 7 || cu["total_tokens"] != 22 {
		t.Fatalf("chat usage=%v", cu)
	}
}

// TestParseImageSizeCases P2.8：尺寸解析。
func TestParseImageSizeCases(t *testing.T) {
	if w, h := ParseImageSize("1024x1024"); w != 1024 || h != 1024 {
		t.Fatalf("got %d,%d", w, h)
	}
	if w, h := ParseImageSize("2048,1024"); w != 2048 || h != 1024 {
		t.Fatalf("got %d,%d", w, h)
	}
	if w, h := ParseImageSize("abc"); w != 1024 || h != 1024 {
		t.Fatalf("fallback got %d,%d", w, h)
	}
}

// TestImageSizeFromBytesCases P2.8：字节解码尺寸。
func TestImageSizeFromBytesCases(t *testing.T) {
	img := image.NewRGBA(image.Rect(0, 0, 320, 200))
	for y := 0; y < 200; y++ {
		for x := 0; x < 320; x++ {
			img.Set(x, y, color.RGBA{R: 1, A: 255})
		}
	}
	var buf bytes.Buffer
	if err := png.Encode(&buf, img); err != nil {
		t.Fatal(err)
	}
	if w, h, ok := ImageSizeFromBytes(buf.Bytes()); !ok || w != 320 || h != 200 {
		t.Fatalf("got %d,%d,%v", w, h, ok)
	}
	if _, _, ok := ImageSizeFromBytes([]byte("not an image")); ok {
		t.Fatal("garbage should fail")
	}
}
