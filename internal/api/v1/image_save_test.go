package v1

import (
	"bytes"
	"encoding/base64"
	"image"
	"image/color"
	"image/jpeg"
	"os"
	"path/filepath"
	"testing"
)

// TestSaveJPEGImagesDecodesBase64 防止「写出 base64 文本冒充 jpg」的回归。
func TestSaveJPEGImagesDecodesBase64(t *testing.T) {
	img := image.NewRGBA(image.Rect(0, 0, 4, 4))
	img.Set(0, 0, color.RGBA{R: 200, A: 255})
	var buf bytes.Buffer
	if err := jpeg.Encode(&buf, img, nil); err != nil {
		t.Fatal(err)
	}
	encoded := base64.StdEncoding.EncodeToString(buf.Bytes())

	dir := t.TempDir()
	paths := saveJPEGImages([][]byte{[]byte(encoded)}, dir)
	if len(paths) != 1 {
		t.Fatalf("want 1 path, got %d", len(paths))
	}
	full := filepath.Join(dir, "images", filepath.FromSlash(paths[0]))
	data, err := os.ReadFile(full)
	if err != nil {
		t.Fatalf("read saved: %v", err)
	}
	if len(data) < 2 || data[0] != 0xFF || data[1] != 0xD8 {
		t.Fatalf("saved file is not JPEG, magic=%x", data[:min(8, len(data))])
	}
	if _, err := jpeg.Decode(bytes.NewReader(data)); err != nil {
		t.Fatalf("saved file not decodable as JPEG: %v", err)
	}
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
