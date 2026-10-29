package backend

import (
	"bytes"
	"image"
	"image/color"
	"image/jpeg"
	"image/png"
	"testing"
)

func TestToJPEGFromPNG(t *testing.T) {
	img := image.NewRGBA(image.Rect(0, 0, 2, 2))
	img.Set(0, 0, color.RGBA{R: 255, A: 255})
	var in bytes.Buffer
	if err := png.Encode(&in, img); err != nil {
		t.Fatal(err)
	}
	out, contentType, err := toJPEG(in.Bytes(), "image/png")
	if err != nil {
		t.Fatalf("toJPEG: %v", err)
	}
	if contentType != "image/jpeg" || !isJPEG(out) {
		t.Fatalf("not a real JPEG: type=%s magic=%x", contentType, out[:2])
	}
	decoded, err := jpeg.Decode(bytes.NewReader(out))
	if err != nil || decoded.Bounds().Dx() != 2 {
		t.Fatalf("decoded JPEG invalid: %v", err)
	}
}

func TestToJPEGKeepsJPEG(t *testing.T) {
	img := image.NewRGBA(image.Rect(0, 0, 1, 1))
	var in bytes.Buffer
	if err := jpeg.Encode(&in, img, nil); err != nil {
		t.Fatal(err)
	}
	out, _, err := toJPEG(in.Bytes(), "image/jpeg")
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(out, in.Bytes()) {
		t.Fatal("JPEG input should not be recompressed")
	}
}
