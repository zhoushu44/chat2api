package v1

import (
	"os"
	"path/filepath"
	"time"
)

// imageDataDir 图片落盘根目录（由路由层注入真实 data 目录）。
var imageDataDir = "data"

// SetImageDataDir 注入数据目录，供 URL 模式落盘 JPG 使用。
func SetImageDataDir(dir string) {
	if dir != "" {
		imageDataDir = dir
	}
}

// DataDir 当前图片落盘根目录。
func DataDir() string { return imageDataDir }

// saveJPEGImages 把已转码的 JPEG 字节落盘到 data/images/YYYYMMDD/，
// 返回可通过 /v1/images/<rel> 访问的相对路径。
// 用于 response_format=url：确保 2K/4K 也返回 JPG，而不是上游原始 URL（可能是 PNG/WebP）。
func saveJPEGImages(datas [][]byte, baseDir string) []string {
	if len(datas) == 0 {
		return nil
	}
	if baseDir == "" {
		baseDir = "data/images"
	}
	dir := filepath.Join(baseDir, time.Now().Format("20060102"))
	if err := os.MkdirAll(dir, 0755); err != nil {
		return nil
	}
	out := make([]string, 0, len(datas))
	stamp := time.Now().Format("150405")
	for i, data := range datas {
		if len(data) == 0 {
			continue
		}
		name := stamp + "_" + itoa(i) + ".jpg"
		if err := os.WriteFile(filepath.Join(dir, name), data, 0644); err != nil {
			continue
		}
		out = append(out, time.Now().Format("20060102")+"/"+name)
	}
	return out
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	var b [8]byte
	i := len(b)
	for n > 0 {
		i--
		b[i] = byte('0' + n%10)
		n /= 10
	}
	return string(b[i:])
}
