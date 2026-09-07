package image

import (
	"archive/zip"
	"errors"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

// Thumbnail 生成缩略图（P1.1 修复：此前写空白图）。
// 对等 image_service.py ensure_thumbnail：EXIF 转置 + 等比缩放（不放大）+ PNG 输出。
func Thumbnail(srcPath, dstPath string, maxSize int) error {
	return LanczosThumbnail(srcPath, dstPath, maxSize)
}

// ZipImages 打包下载（对等 image_service.py 553-582：路径越权防护 + 重名 _2 后缀 + 空结果 404）。
func ZipImages(paths []string, zipPath string) error {
	f, err := os.Create(zipPath)
	if err != nil {
		return err
	}
	defer f.Close()
	w := zip.NewWriter(f)
	defer w.Close()
	used := make(map[string]int)
	added := 0
	for _, p := range paths {
		// 路径越权防护：拒绝 .. 上跳（绝对路径由调用方约束，见 zipRooted）
		clean := filepath.ToSlash(filepath.Clean(p))
		if strings.Contains(clean, "../") || clean == ".." {
			continue
		}
		data, err := os.ReadFile(p)
		if err != nil {
			continue
		}
		name := filepath.Base(p)
		if used[name] > 0 {
			// 重名自动 _2 后缀（对齐 Python）
			ext := filepath.Ext(name)
			stem := strings.TrimSuffix(name, ext)
			used[name]++
			name = stem + "_" + strconv.Itoa(used[name]+1) + ext
		} else {
			used[name] = 1
		}
		fw, err := w.Create(name)
		if err != nil {
			continue
		}
		if _, err := fw.Write(data); err == nil {
			added++
		}
	}
	if added == 0 {
		return ErrNoImages
	}
	return nil
}

// ErrNoImages 空结果（对齐 Python 404 语义）。
var ErrNoImages = errors.New("no images to zip")
func Cleanup(dir string, retain time.Duration) error {
	now := time.Now()
	return filepath.Walk(dir, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return nil
		}
		if !info.IsDir() && now.Sub(info.ModTime()) > retain {
			_ = os.Remove(path)
		}
		return nil
	})
}
