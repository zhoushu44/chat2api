// Package imageclean 图片自动清理：按保留天数删除 <DataDir>/images/ 下的过期日期目录。
// 保留天数每次巡检动态读取 config（image_retention_days，设置面板可改，热生效）。
package imageclean

import (
	"log"
	"os"
	"path/filepath"
	"strconv"
	"sync"
	"time"

	"chatgpt2api/internal/config"
)

// Cleaner 定期清理器（每小时巡检一次，日期目录 YYYYMMDD 早于保留窗口的整个删除）。
type Cleaner struct {
	DataDir string
	// RetentionDays 动态保留天数（nil 时读全局 config.image_retention_days）。
	RetentionDays func() int
	// Interval 巡检间隔（测试可注入短间隔；零值默认 1 小时）。
	Interval time.Duration

	mu     sync.Mutex
	stopCh chan struct{}
	once   sync.Once
}

// Start 启动后台巡检（幂等）。
func (c *Cleaner) Start() {
	c.mu.Lock()
	if c.stopCh != nil {
		c.mu.Unlock()
		return
	}
	c.stopCh = make(chan struct{})
	stopCh := c.stopCh
	c.mu.Unlock()
	go c.loop(stopCh)
}

// Stop 停止巡检。
func (c *Cleaner) Stop() {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.stopCh != nil {
		close(c.stopCh)
		c.stopCh = nil
	}
}

func (c *Cleaner) loop(stopCh <-chan struct{}) {
	interval := c.Interval
	if interval <= 0 {
		interval = time.Hour
	}
	// 启动先清一次，再周期巡检
	c.CleanupOnce()
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		select {
		case <-stopCh:
			return
		case <-ticker.C:
			c.CleanupOnce()
		}
	}
}

// retentionDays 当前保留天数（<=0 视为未配置，用默认 15）。
func (c *Cleaner) retentionDays() int {
	days := 0
	if c.RetentionDays != nil {
		days = c.RetentionDays()
	}
	if days <= 0 {
		days = config.Get().ImageRetentionDays
	}
	if days <= 0 {
		days = 15
	}
	return days
}

// CleanupOnce 执行一次清理，返回删除的目录数。目录名必须是 8 位日期，
// 早于「今天 - 保留天数」的整个目录删除；解析失败/未来日期的目录不动。
func (c *Cleaner) CleanupOnce() int {
	dir := c.ImagesRoot()
	entries, err := os.ReadDir(dir)
	if err != nil {
		return 0 // 目录不存在：无图可清，正常
	}
	days := c.retentionDays()
	cutoff := time.Now().AddDate(0, 0, -days).Format("20060102")
	removed := 0
	for _, e := range entries {
		if !e.IsDir() || !isDateDir(e.Name()) {
			continue
		}
		if e.Name() >= cutoff {
			continue
		}
		if err := os.RemoveAll(filepath.Join(dir, e.Name())); err != nil {
			log.Printf("[image-clean] 删除 %s 失败: %v", e.Name(), err)
			continue
		}
		removed++
	}
	if removed > 0 {
		log.Printf("[image-clean] 已清理 %d 个过期图片目录（保留 %d 天）", removed, days)
	}
	return removed
}

// ImagesRoot 图片根目录（与 gallery / archiver 同口径）。
func (c *Cleaner) ImagesRoot() string {
	base := c.DataDir
	if base == "" {
		base = "data"
	}
	return filepath.Join(base, "images")
}

func isDateDir(name string) bool {
	if len(name) != 8 {
		return false
	}
	if _, err := strconv.Atoi(name); err != nil {
		return false
	}
	if _, err := time.Parse("20060102", name); err != nil {
		return false
	}
	return true
}
