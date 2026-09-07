// Package metrics 仪表盘指标（P1.7：对等 dashboard_metrics_service.py）。
// 日/小时双桶聚合 + dashboard_metrics.json 持久化（debounced flush）+ 30 天保留 +
// summary(24h/7d/30d) 趋势序列。Beijing 时区（UTC+8，对齐 Python beijing_now）。
package metrics

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"
)

// CallEvent 单次调用记录（对等 record_call_log 的 item）。
type CallEvent struct {
	Status    string    // success | error | rate_limited 等
	Endpoint  string    // /v1/images/generations
	Model     string    // gpt-image-2
	ErrorCode string    // insufficient_quota / upstream_error
	Duration  float64   // ms
	At        time.Time // 默认 now
}

// Bucket 单桶计数（对等 _empty_bucket）。
type Bucket struct {
	Total           int              `json:"total"`
	Success         int              `json:"success"`
	Failed          int              `json:"failed"`
	TextReview      int              `json:"text_review"`
	RateLimited     int              `json:"rate_limited"`
	ByEndpoint      map[string]int   `json:"by_endpoint"`
	ByModel         map[string]int   `json:"by_model"`
	ByStatus        map[string]int   `json:"by_status"`
	ByErrorCode     map[string]int   `json:"by_error_code"`
	ModelTotalTimes map[string]float64 `json:"model_total_times"`
	ModelTimeCounts map[string]int     `json:"model_time_counts"`
	Hours           map[string]*Bucket `json:"hours,omitempty"`
}

func newBucket() *Bucket {
	return &Bucket{
		ByEndpoint:      map[string]int{},
		ByModel:         map[string]int{},
		ByStatus:        map[string]int{},
		ByErrorCode:     map[string]int{},
		ModelTotalTimes: map[string]float64{},
		ModelTimeCounts: map[string]int{},
	}
}

// Metrics 指标服务。
type Metrics struct {
	mu      sync.Mutex
	dir     string
	days    map[string]*Bucket // 内存工作集（pending，flush 时合并落盘）
	dirty   bool
	timer   *time.Timer
	stopped bool
}

const (
	fileName     = "dashboard_metrics.json"
	flushDelay   = 2 * time.Second
	retentionDay = 30
)

// New 纯内存服务；NewWithDir 带持久化。
func New() *Metrics {
	return &Metrics{days: map[string]*Bucket{}}
}

// NewWithDir 持久化目录（读已有 dashboard_metrics.json）。
func NewWithDir(dir string) *Metrics {
	m := New()
	m.dir = dir
	if b, err := os.ReadFile(filepath.Join(dir, fileName)); err == nil {
		var data struct {
			Days map[string]*Bucket `json:"days"`
		}
		if err := json.Unmarshal(b, &data); err == nil && data.Days != nil {
			for k, v := range data.Days {
				m.days[k] = normalizeBucket(v)
			}
		}
	}
	return m
}

// normalizeBucket 补齐 nil map（兼容旧文件）。
func normalizeBucket(b *Bucket) *Bucket {
	if b == nil {
		return newBucket()
	}
	if b.ByEndpoint == nil {
		b.ByEndpoint = map[string]int{}
	}
	if b.ByModel == nil {
		b.ByModel = map[string]int{}
	}
	if b.ByStatus == nil {
		b.ByStatus = map[string]int{}
	}
	if b.ByErrorCode == nil {
		b.ByErrorCode = map[string]int{}
	}
	if b.ModelTotalTimes == nil {
		b.ModelTotalTimes = map[string]float64{}
	}
	if b.ModelTimeCounts == nil {
		b.ModelTimeCounts = map[string]int{}
	}
	for k, h := range b.Hours {
		b.Hours[k] = normalizeBucket(h)
	}
	return b
}

// beijing 当地时间（UTC+8）。
func beijing(t time.Time) time.Time {
	return t.In(time.FixedZone("CST", 8*3600))
}

// Record 记录一次调用（日桶+小时桶，对等 record_call_log）。
func (m *Metrics) Record(ev CallEvent) {
	at := ev.At
	if at.IsZero() {
		at = time.Now()
	}
	bj := beijing(at)
	dayKey := bj.Format("2006-01-02")
	hourKey := bj.Format("15")
	m.mu.Lock()
	defer m.mu.Unlock()
	day := m.days[dayKey]
	if day == nil {
		day = newBucket()
		m.days[dayKey] = day
	}
	applyCall(day, ev)
	if day.Hours == nil {
		day.Hours = map[string]*Bucket{}
	}
	hour := day.Hours[hourKey]
	if hour == nil {
		hour = newBucket()
		day.Hours[hourKey] = hour
	}
	applyCall(hour, ev)
	m.markDirtyLocked()
}

// applyCall 单条事件累加到桶（对等 _apply_call）。
func applyCall(b *Bucket, ev CallEvent) {
	status := strings.ToLower(strings.TrimSpace(ev.Status))
	b.Total++
	switch {
	case isTextReview(status, ev.ErrorCode):
		b.TextReview++
	case isFailure(status):
		b.Failed++
		if isRateLimit(status, ev.ErrorCode) {
			b.RateLimited++
		}
	default:
		b.Success++
	}
	if status != "" {
		b.ByStatus[status]++
	}
	if strings.HasPrefix(ev.Endpoint, "/") {
		b.ByEndpoint[ev.Endpoint]++
	}
	if looksLikeModel(ev.Model) {
		b.ByModel[ev.Model]++
		if ev.Duration >= 0 {
			b.ModelTotalTimes[ev.Model] += ev.Duration
			b.ModelTimeCounts[ev.Model]++
		}
	}
	if ev.ErrorCode != "" {
		b.ByErrorCode[strings.ToLower(ev.ErrorCode)]++
	}
}

func isTextReview(status, code string) bool {
	return strings.Contains(strings.ToLower(code), "text_review") ||
		strings.Contains(status, "text_review")
}

func isFailure(status string) bool {
	return status != "" && status != "success" && status != "ok"
}

func isRateLimit(status, code string) bool {
	return strings.Contains(status, "rate_limit") || strings.Contains(code, "rate_limit") ||
		strings.Contains(code, "insufficient_quota")
}

func looksLikeModel(model string) bool {
	model = strings.TrimSpace(model)
	return model != "" && model != "unknown"
}

// markDirtyLocked 标记脏 + 调度 flush（对等 _mark_dirty_locked）。
func (m *Metrics) markDirtyLocked() {
	m.dirty = true
	if m.dir == "" || m.stopped {
		return
	}
	if m.timer != nil {
		return
	}
	m.timer = time.AfterFunc(flushDelay, m.flushDue)
}

func (m *Metrics) flushDue() {
	m.mu.Lock()
	m.timer = nil
	m.mu.Unlock()
	_ = m.Flush()
}

// Flush 合并落盘 + 保留期裁剪（对等 flush）。
func (m *Metrics) Flush() error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.dir == "" || !m.dirty {
		return nil
	}
	m.pruneLocked(beijing(time.Now()))
	payload := struct {
		Version int                `json:"version"`
		Days    map[string]*Bucket `json:"days"`
	}{Version: 1, Days: m.days}
	b, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	tmp := filepath.Join(m.dir, fileName+".tmp")
	if err := os.WriteFile(tmp, b, 0644); err != nil {
		return err
	}
	if err := os.Rename(tmp, filepath.Join(m.dir, fileName)); err != nil {
		return err
	}
	m.dirty = false
	return nil
}

// pruneLocked 保留期裁剪（对等 _prune，默认 30 天）。
func (m *Metrics) pruneLocked(now time.Time) {
	cutoff := now.AddDate(0, 0, -(retentionDay - 1)).Format("2006-01-02")
	today := now.Format("2006-01-02")
	for day := range m.days {
		if len(day) != 10 || day < cutoff || day > today {
			delete(m.days, day)
		}
	}
}

// Summary 趋势汇总（对等 summary；24h→24 小时点，7d/30d→按天）。
// 返回 labels + 每点桶数据（含 success_rate）。
func (m *Metrics) Summary(timeRange string) map[string]any {
	count := 24
	byHour := true
	switch timeRange {
	case "7d":
		count, byHour = 7, false
	case "30d":
		count, byHour = 30, false
	default:
		timeRange = "24h"
	}
	now := beijing(time.Now())
	labels := make([]string, 0, count)
	series := make([]map[string]any, 0, count)
	total := newBucket()
	m.mu.Lock()
	// 深拷贝快照后释放锁
	days := map[string]*Bucket{}
	for k, v := range m.days {
		days[k] = v
	}
	m.mu.Unlock()
	for i := count - 1; i >= 0; i-- {
		var label string
		var bucket *Bucket
		if byHour {
			t := now.Add(-time.Duration(i) * time.Hour)
			label = t.Format("15:00")
			if day := days[t.Format("2006-01-02")]; day != nil && day.Hours != nil {
				bucket = day.Hours[t.Format("15")]
			}
		} else {
			t := now.AddDate(0, 0, -i)
			label = t.Format("01-02")
			bucket = days[t.Format("2006-01-02")]
		}
		if bucket == nil {
			bucket = newBucket()
		}
		labels = append(labels, label)
		mergeBucket(total, bucket)
		series = append(series, bucketView(bucket))
	}
	return map[string]any{
		"time_range": timeRange,
		"labels":     labels,
		"series":     series,
		"total":      bucketView(total),
	}
}

// bucketView 桶对外视图（含成功率与模型平均耗时）。
func bucketView(b *Bucket) map[string]any {
	rate := 0.0
	if b.Total > 0 {
		rate = float64(b.Success) / float64(b.Total)
	}
	avgTimes := map[string]float64{}
	for model, total := range b.ModelTotalTimes {
		if n := b.ModelTimeCounts[model]; n > 0 {
			avgTimes[model] = total / float64(n)
		}
	}
	return map[string]any{
		"total":             b.Total,
		"success":           b.Success,
		"failed":            b.Failed,
		"text_review":       b.TextReview,
		"rate_limited":      b.RateLimited,
		"success_rate":      rate,
		"by_endpoint":       b.ByEndpoint,
		"by_model":          b.ByModel,
		"by_status":         b.ByStatus,
		"by_error_code":     b.ByErrorCode,
		"model_avg_times":   avgTimes,
	}
}

// mergeBucket 桶合并（对等 _merge_bucket）。
func mergeBucket(dst, src *Bucket) {
	dst.Total += src.Total
	dst.Success += src.Success
	dst.Failed += src.Failed
	dst.TextReview += src.TextReview
	dst.RateLimited += src.RateLimited
	for k, v := range src.ByEndpoint {
		dst.ByEndpoint[k] += v
	}
	for k, v := range src.ByModel {
		dst.ByModel[k] += v
	}
	for k, v := range src.ByStatus {
		dst.ByStatus[k] += v
	}
	for k, v := range src.ByErrorCode {
		dst.ByErrorCode[k] += v
	}
	for k, v := range src.ModelTotalTimes {
		dst.ModelTotalTimes[k] += v
	}
	for k, v := range src.ModelTimeCounts {
		dst.ModelTimeCounts[k] += v
	}
}

// Days 返回天键列表（测试用）。
func (m *Metrics) Days() []string {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := make([]string, 0, len(m.days))
	for k := range m.days {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}
