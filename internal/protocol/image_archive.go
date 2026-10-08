// Package protocol 图片存档：生图成功后落盘 <DataDir>/images/YYYYMMDD/，
// 供控制台「图片管理」页浏览（gallery 扫描同一目录）。
package protocol

import (
	"fmt"
	"os"
	"path/filepath"
	"time"
)

// ImageArchiver 生图存档器。
// EnabledFunc 每次存档前动态求值（支持设置面板热更开关，无需重启）。
type ImageArchiver struct {
	DataDir     string
	EnabledFunc func() bool
}

// Archive 把一张已下载的图片字节落盘，返回相对路径（YYYYMMDD/name，gallery 契约）。
// 写失败只记 stderr，不影响主链路（存档是旁路，绝不阻断生图响应）。
func (a *ImageArchiver) Archive(data []byte, index int) string {
	if a == nil || len(data) == 0 {
		return ""
	}
	if a.EnabledFunc != nil && !a.EnabledFunc() {
		return ""
	}
	dateDir := time.Now().Format("20060102")
	dir := filepath.Join(a.baseDir(), "images", dateDir)
	if err := os.MkdirAll(dir, 0755); err != nil {
		fmt.Fprintf(os.Stderr, "[image-archive] mkdir %s: %v\n", dir, err)
		return ""
	}
	name := fmt.Sprintf("%s_%d.png", time.Now().Format("150405"), index)
	full := filepath.Join(dir, name)
	tmp := full + ".tmp"
	if err := os.WriteFile(tmp, data, 0644); err != nil {
		fmt.Fprintf(os.Stderr, "[image-archive] write %s: %v\n", tmp, err)
		return ""
	}
	if err := os.Rename(tmp, full); err != nil {
		_ = os.Remove(tmp)
		fmt.Fprintf(os.Stderr, "[image-archive] rename %s: %v\n", full, err)
		return ""
	}
	return filepath.ToSlash(filepath.Join(dateDir, name))
}

func (a *ImageArchiver) baseDir() string {
	if a == nil || a.DataDir == "" {
		return "data"
	}
	return a.DataDir
}
