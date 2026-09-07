package image

import (
	"bytes"
	"image"
	"image/jpeg"
	"io"
)

// exifTranspose 按 EXIF Orientation 转置（对等 PIL ImageOps.exif_transpose）。
// JPEG EXIF（APP1 段）Orientation 值 1-8：5-8 为旋转，3/6/8 为 90° 步进，2/4/6/7 含镜像。
func exifTranspose(src image.Image) image.Image {
	// 仅 JPEG 携带 EXIF
	if _, ok := src.(*image.YCbCr); !ok {
		// 非 JPEG 解码结果（PNG 等无 EXIF）原样返回
		return src
	}
	// 重新编码再读 EXIF：image.Image 不保留原始字节，标准库无 EXIF 直读。
	// 此处通过 JPEG 编码后解析 APP1 提取 Orientation。
	var buf bytes.Buffer
	if err := jpeg.Encode(&buf, src, &jpeg.Options{Quality: 95}); err != nil {
		return src
	}
	orientation, ok := readExifOrientation(buf.Bytes())
	if !ok || orientation <= 1 || orientation > 8 {
		return src
	}
	return applyOrientation(src, orientation)
}

// readExifOrientation 从 JPEG 字节流解析 EXIF Orientation（tag 0x0112）。
func readExifOrientation(jpegBytes []byte) (int, bool) {
	// 扫描 JPEG 段
	if len(jpegBytes) < 4 || jpegBytes[0] != 0xFF || jpegBytes[1] != 0xD8 {
		return 0, false
	}
	pos := 2
	for pos+4 <= len(jpegBytes) {
		if jpegBytes[pos] != 0xFF {
			return 0, false
		}
		marker := jpegBytes[pos+1]
		if marker == 0xDA || marker == 0xD9 { // SOS/EOI：EXIF 段只在头部
			return 0, false
		}
		segLen := int(jpegBytes[pos+2])<<8 | int(jpegBytes[pos+3])
		if marker == 0xE1 && segLen >= 8 && pos+2+segLen <= len(jpegBytes) {
			// APP1: "Exif\0\0" + TIFF
			body := jpegBytes[pos+4 : pos+2+segLen]
			if len(body) >= 6 && string(body[:6]) == "Exif\x00\x00" {
				return parseTiffOrientation(body[6:])
			}
		}
		pos += 2 + segLen
	}
	return 0, false
}

// parseTiffOrientation 解析 TIFF 头内 IFD0 的 Orientation tag。
func parseTiffOrientation(tiff []byte) (int, bool) {
	if len(tiff) < 8 {
		return 0, false
	}
	var little bool
	switch {
	case tiff[0] == 'I' && tiff[1] == 'I':
		little = true
	case tiff[0] == 'M' && tiff[1] == 'M':
		little = false
	default:
		return 0, false
	}
	u16 := func(b []byte) int {
		if little {
			return int(b[0]) | int(b[1])<<8
		}
		return int(b[0])<<8 | int(b[1])
	}
	u32 := func(b []byte) int {
		if little {
			return int(b[0]) | int(b[1])<<8 | int(b[2])<<16 | int(b[3])<<24
		}
		return int(b[0])<<24 | int(b[1])<<16 | int(b[2])<<8 | int(b[3])
	}
	ifdOff := u32(tiff[4:8])
	if ifdOff+2 > len(tiff) {
		return 0, false
	}
	count := u16(tiff[ifdOff : ifdOff+2])
	for i := 0; i < count; i++ {
		e := ifdOff + 2 + i*12
		if e+12 > len(tiff) {
			return 0, false
		}
		tag := u16(tiff[e : e+2])
		if tag == 0x0112 {
			// value 由 type/size 决定，SHORT 在条目内联
			return u16(tiff[e+8 : e+10]), true
		}
	}
	return 0, false
}

// applyOrientation 按 orientation 1-8 生成转置图像。
func applyOrientation(src image.Image, orientation int) image.Image {
	bounds := src.Bounds()
	w, h := bounds.Dx(), bounds.Dy()
	transpose := orientation >= 5 // 5-8 交换宽高
	var nw, nh int
	if transpose {
		nw, nh = h, w
	} else {
		nw, nh = w, h
	}
	dst := image.NewRGBA(image.Rect(0, 0, nw, nh))
	for y := 0; y < h; y++ {
		for x := 0; x < w; x++ {
			dx, dy := x, y
			switch orientation {
			case 2: // 水平镜像
				dx = w - 1 - x
			case 3: // 180
				dx, dy = w-1-x, h-1-y
			case 4: // 垂直镜像
				dy = h - 1 - y
			case 5: // 转置（主对角线）
				dx, dy = y, x
			case 6: // 90° 顺时针
				dx, dy = y, w-1-x
			case 7: // 反转置
				dx, dy = h-1-y, w-1-x
			case 8: // 90° 逆时针
				dx, dy = h-1-y, x
			}
			dst.Set(dx, dy, src.At(bounds.Min.X+x, bounds.Min.Y+y))
		}
	}
	return dst
}

var _ = io.Discard
