package image

import (
	"image"
	"image/color"
	"image/jpeg"
	"image/png"
	"os"
	"strings"
)

// LanczosThumbnail 真实缩略图（P1.1 修复）：
// 对等 image_service.py ensure_thumbnail —— EXIF 转置 + 等比缩放 + LANCZOS 级质量。
// 实现：双三次（Catmull-Rom）插值，LANCZOS 的标准低成本近似，远优于旧最近邻/空白图。
func LanczosThumbnail(srcPath, dstPath string, maxSize int) error {
	f, err := os.Open(srcPath)
	if err != nil {
		return err
	}
	defer f.Close()
	src, _, err := image.Decode(f)
	if err != nil {
		return err
	}
	src = exifTranspose(src)
	dst := bicubicResize(src, maxSize)
	out, err := os.Create(dstPath)
	if err != nil {
		return err
	}
	defer out.Close()
	if strings.HasSuffix(strings.ToLower(dstPath), ".jpg") || strings.HasSuffix(strings.ToLower(dstPath), ".jpeg") {
		return jpeg.Encode(out, dst, &jpeg.Options{Quality: 90})
	}
	return png.Encode(out, dst)
}

// bicubicResize 等比缩放到 maxSize 内（对等 PIL image.thumbnail(THUMBNAIL_SIZE, LANCZOS)，
// 仅缩小不放大，对齐 Python 行为）。
func bicubicResize(src image.Image, maxSize int) *image.RGBA {
	bounds := src.Bounds()
	w, h := bounds.Dx(), bounds.Dy()
	if w == 0 || h == 0 {
		return image.NewRGBA(image.Rect(0, 0, 1, 1))
	}
	scale := float64(maxSize) / float64(max(w, h))
	if scale >= 1 {
		// 不放大：原尺寸输出
		scale = 1
	}
	nw, nh := maxInt(1, int(float64(w)*scale+0.5)), maxInt(1, int(float64(h)*scale+0.5))
	dst := image.NewRGBA(image.Rect(0, 0, nw, nh))
	// 采样中心对齐
	xRatio := float64(w) / float64(nw)
	yRatio := float64(h) / float64(nh)
	for y := 0; y < nh; y++ {
		sy := (float64(y)+0.5)*yRatio - 0.5
		for x := 0; x < nw; x++ {
			sx := (float64(x)+0.5)*xRatio - 0.5
			dst.SetRGBA(x, y, bicubicSample(src, bounds, sx, sy))
		}
	}
	return dst
}

// bicubicSample Catmull-Rom 双三次采样（a=-0.5）。
// sx/sy 为源坐标（相对 bounds.Min），返回采样颜色。
func bicubicSample(src image.Image, bounds image.Rectangle, sx, sy float64) color.RGBA {
	x0, y0 := int(sx), int(sy)
	fx, fy := sx-float64(x0), sy-float64(y0)
	var r, g, b, a float64
	// 4x4 加权（源坐标 → bounds 内绝对坐标）
	for m := -1; m <= 2; m++ {
		wy := catmullRom(fy - float64(m))
		for n := -1; n <= 2; n++ {
			wx := catmullRom(fx - float64(n))
			w := wx * wy
			if w == 0 {
				continue
			}
			px := clampInt(bounds.Min.X+x0+n, bounds.Min.X, bounds.Max.X-1)
			py := clampInt(bounds.Min.Y+y0+m, bounds.Min.Y, bounds.Max.Y-1)
			pr, pg, pb, pa := src.At(px, py).RGBA()
			r += w * float64(pr>>8)
			g += w * float64(pg>>8)
			b += w * float64(pb>>8)
			a += w * float64(pa>>8)
		}
	}
	return color.RGBA{R: uint8(clampF(r)), G: uint8(clampF(g)), B: uint8(clampF(b)), A: uint8(clampF(a))}
}

// catmullRom 权重核（a=-0.5，PIL LANCZOS 的常见近似）。
func catmullRom(t float64) float64 {
	t = absF(t)
	if t < 1 {
		return (1.5*t-2.5)*t*t + 1
	}
	if t < 2 {
		return ((-0.5*t+2.5)*t-4)*t + 2
	}
	return 0
}

func absF(v float64) float64 {
	if v < 0 {
		return -v
	}
	return v
}

func clampF(v float64) int {
	if v < 0 {
		return 0
	}
	if v > 255 {
		return 255
	}
	return int(v + 0.5)
}

func clampInt(v, lo, hi int) int {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}

func maxInt(a, b int) int {
	if a > b {
		return a
	}
	return b
}
