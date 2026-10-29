package backend

import (
	"bytes"
	"image"
	"image/color"
	"image/draw"
	"image/jpeg"
	_ "image/gif"
	_ "image/png"
	_ "golang.org/x/image/webp"
)

// toJPEG 将上游返回的 PNG/WebP/GIF 统一转成真正的 JPEG。
// 只改字节编码，不只是改扩展名；已是 JPEG 的输入原样返回，避免重复压缩。
// 透明像素以白色背景合成，避免 JPG 不支持透明导致黑底。
func toJPEG(data []byte, contentType string) ([]byte, string, error) {
	if isJPEG(data) {
		return data, "image/jpeg", nil
	}
	img, _, err := image.Decode(bytes.NewReader(data))
	if err != nil {
		return nil, "", err
	}
	bounds := img.Bounds()
	out := image.NewRGBA(bounds)
	draw.Draw(out, bounds, image.NewUniform(color.White), image.Point{}, draw.Src)
	draw.Draw(out, bounds, img, bounds.Min, draw.Over)
	var buf bytes.Buffer
	if err := jpeg.Encode(&buf, out, &jpeg.Options{Quality: 90}); err != nil {
		return nil, "", err
	}
	return buf.Bytes(), "image/jpeg", nil
}

func isJPEG(data []byte) bool {
	return len(data) >= 2 && data[0] == 0xFF && data[1] == 0xD8
}
