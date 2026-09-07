package image

import (
	"archive/zip"
	"bytes"
	"image"
	"image/color"
	"image/jpeg"
	"image/png"
	"os"
	"path/filepath"
	"testing"
)

// gradient 生成左红右蓝的两半图（左 1/3 纯红、右 1/3 纯蓝），用于验证像素真实保留。
// 缩略 4x 后左半仍应红、右半仍应蓝——空白图则两者皆黑。
func gradient(w, h int) *image.RGBA {
	img := image.NewRGBA(image.Rect(0, 0, w, h))
	for y := 0; y < h; y++ {
		for x := 0; x < w; x++ {
			c := color.RGBA{R: 255, A: 255}
			if x >= w*2/3 {
				c = color.RGBA{B: 255, A: 255}
			}
			img.SetRGBA(x, y, c)
		}
	}
	return img
}

// TestThumbnail_PixelsPreserved P1.1 验收：缩略图必须保留源图像素（修复前写全黑空白图）。
func TestThumbnail_PixelsPreserved(t *testing.T) {
	dir := t.TempDir()
	src := filepath.Join(dir, "src.png")
	f, _ := os.Create(src)
	_ = png.Encode(f, gradient(200, 100))
	f.Close()
	dst := filepath.Join(dir, "thumb.png")
	if err := Thumbnail(src, dst, 50); err != nil {
		t.Fatal(err)
	}
	in, err := os.Open(dst)
	if err != nil {
		t.Fatal(err)
	}
	defer in.Close()
	img, _, err := image.Decode(in)
	if err != nil {
		t.Fatal(err)
	}
	b := img.Bounds()
	if b.Dx() != 50 || b.Dy() != 25 {
		t.Fatalf("size %dx%d want 50x25 (aspect 2:1)", b.Dx(), b.Dy())
	}
	// 像素校验（区域均值，抗双三次边缘混合）：左侧 1/3 区域平均 R 应 > 200，
	// 右侧 1/3 区域平均 B 应 > 200 —— 空白图两者皆 0。
	sumRLeft, sumBRight, nLeft, nRight := 0, 0, 0, 0
	third := b.Dx() / 3
	for y := 0; y < b.Dy(); y++ {
		for x := 0; x < third; x++ {
			r, _, _, _ := img.At(x, y).RGBA()
			sumRLeft += int(r >> 8)
			nLeft++
		}
		for x := b.Dx() - third; x < b.Dx(); x++ {
			_, _, bb, _ := img.At(x, y).RGBA()
			sumBRight += int(bb >> 8)
			nRight++
		}
	}
	if avgR := sumRLeft / maxInt1(nLeft); avgR < 200 {
		t.Fatalf("left region avg R=%d want >=200 (blank-image bug?)", avgR)
	}
	if avgB := sumBRight / maxInt1(nRight); avgB < 200 {
		t.Fatalf("right region avg B=%d want >=200 (blank-image bug?)", avgB)
	}
}

func maxInt1(v int) int {
	if v < 1 {
		return 1
	}
	return v
}

// TestThumbnail_NoUpscale 对齐 PIL thumbnail：不放大。
func TestThumbnail_NoUpscale(t *testing.T) {
	dir := t.TempDir()
	src := filepath.Join(dir, "tiny.png")
	f, _ := os.Create(src)
	_ = png.Encode(f, gradient(30, 30))
	f.Close()
	dst := filepath.Join(dir, "thumb.png")
	if err := Thumbnail(src, dst, 320); err != nil {
		t.Fatal(err)
	}
	in, _ := os.Open(dst)
	defer in.Close()
	img, _, _ := image.Decode(in)
	if img.Bounds().Dx() != 30 {
		t.Fatalf("upscaled to %d, want 30", img.Bounds().Dx())
	}
}

// TestExifTranspose6 P1.1：EXIF orientation=6（90°顺时针）转置。
// 语义对齐 PIL：src(x,y) → dst(y, srcW-1-x)。
func TestExifTranspose6(t *testing.T) {
	// 构造 2x1 图（宽>高）：(0,0)=红 (1,0)=蓝
	src := image.NewRGBA(image.Rect(0, 0, 2, 1))
	src.SetRGBA(0, 0, color.RGBA{R: 255, A: 255})
	src.SetRGBA(1, 0, color.RGBA{B: 255, A: 255})
	out := applyOrientation(src, 6)
	b := out.Bounds()
	if b.Dx() != 1 || b.Dy() != 2 {
		t.Fatalf("bounds %v want 1x2", b)
	}
	// src(0,0)红 → dst(0, 2-1-0)=(0,1)
	r, _, _, _ := out.At(0, 1).RGBA()
	if r>>8 != 255 {
		t.Fatalf("pixel (0,1) not red after transpose: R=%d", r>>8)
	}
	// src(1,0)蓝 → dst(0, 2-1-1)=(0,0)
	_, _, bb, _ := out.At(0, 0).RGBA()
	if bb>>8 != 255 {
		t.Fatalf("pixel (0,0) not blue after transpose: B=%d", bb>>8)
	}
}

// TestReadExifOrientation 解析真实 JPEG EXIF。
func TestReadExifOrientation(t *testing.T) {
	// 手工构造带 EXIF orientation=6 的 JPEG
	jfif := &bytes.Buffer{}
	_ = jpeg.Encode(jfif, image.NewRGBA(image.Rect(0, 0, 4, 4)), nil)
	// 注入 APP1 EXIF 段：构造 TIFF little-endian，IFD0 单条目 tag 0x0112 = 6
	exif := buildExifOrientation(6)
	// 重组：SOI + APP1 + 原JPEG余部（跳过原 SOI）
	out := []byte{0xFF, 0xD8, 0xFF, 0xE1}
	segLen := len(exif) + 2
	out = append(out, byte(segLen>>8), byte(segLen&0xFF))
	out = append(out, exif...)
	out = append(out, jfif.Bytes()[2:]...)
	if v, ok := readExifOrientation(out); !ok || v != 6 {
		t.Fatalf("orientation=%d ok=%v want 6 true", v, ok)
	}
}

// buildExifOrientation 构造最小 EXIF（orientation tag）。
func buildExifOrientation(v int) []byte {
	// "Exif\0\0" + TIFF header + IFD
	tiff := []byte{}
	tiff = append(tiff, 'I', 'I', 0x2A, 0x00) // little-endian magic
	tiff = append(tiff, 0x08, 0x00, 0x00, 0x00) // IFD offset = 8
	// IFD: 1 entry
	tiff = append(tiff, 0x01, 0x00) // count=1
	// entry: tag=0x0112, type=3 (SHORT), count=1, value inline
	tiff = append(tiff, 0x12, 0x01, 0x03, 0x00, 0x01, 0x00, 0x00, 0x00)
	tiff = append(tiff, byte(v), 0x00, 0x00, 0x00)
	// next IFD = 0
	tiff = append(tiff, 0x00, 0x00, 0x00, 0x00)
	exif := append([]byte("Exif\x00\x00"), tiff...)
	return exif
}

// TestZipImagesSafety P1.1：路径越权防护 + 重名后缀 + 空结果错误。
func TestZipImagesSafety(t *testing.T) {
	dir := t.TempDir()
	a := filepath.Join(dir, "a.png")
	b := filepath.Join(dir, "b.png")
	for _, p := range []string{a, b} {
		f, _ := os.Create(p)
		_ = png.Encode(f, gradient(10, 10))
		f.Close()
	}
	zipPath := filepath.Join(dir, "out.zip")
	// 重名：同 basename 两个文件
	if err := ZipImages([]string{a, b, a}, zipPath); err != nil {
		t.Fatal(err)
	}
	zr, err := zip.OpenReader(zipPath)
	if err != nil {
		t.Fatal(err)
	}
	defer zr.Close()
	names := map[string]bool{}
	for _, zf := range zr.File {
		names[zf.Name] = true
	}
	if !names["a.png"] {
		t.Fatalf("missing a.png in %v", names)
	}
	// a.png 出现两次：第二次必须重命名
	hasDup := false
	for n := range names {
		if n != "a.png" && n != "b.png" {
			hasDup = true
		}
	}
	if !hasDup {
		t.Fatalf("duplicate a.png not renamed: %v", names)
	}
	// 空输入 → ErrNoImages
	if err := ZipImages(nil, filepath.Join(dir, "empty.zip")); err != ErrNoImages {
		t.Fatalf("empty input err=%v want ErrNoImages", err)
	}
}

// TestZipImagesPathTraversal P1.1：越权路径（绝对路径/上跳）被拒。
func TestZipImagesPathTraversal(t *testing.T) {
	// 仅有越权路径时：无有效文件 → ErrNoImages（不会读外部文件）
	dir := t.TempDir()
	if err := ZipImages([]string{"C:\\Windows\\system32\\config", "../../etc/passwd"}, filepath.Join(dir, "x.zip")); err != ErrNoImages {
		t.Fatalf("traversal err=%v want ErrNoImages", err)
	}
}
