//go:build !linux

package api

// Windows 等平台没有 syscall.Statfs；返回 0 由前端显示未知，
// 不影响图片列表、下载和删除。
func diskUsage(root string) (total, free uint64) { return 0, 0 }
