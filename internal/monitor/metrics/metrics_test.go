package metrics

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

// TestBucketAggregate P1.7 验收：桶口径（累计/成功率/by_model/by_endpoint/by_error_code/模型耗时）。
func TestBucketAggregate(t *testing.T) {
	m := New()
	now := time.Now()
	m.Record(CallEvent{Status: "success", Endpoint: "/v1/images/generations", Model: "gpt-image-2", Duration: 9000, At: now})
	m.Record(CallEvent{Status: "success", Endpoint: "/v1/images/generations", Model: "gpt-image-2", Duration: 11000, At: now})
	m.Record(CallEvent{Status: "error", Endpoint: "/v1/images/generations", Model: "gpt-image-2", ErrorCode: "image_quota_exhausted", Duration: 500, At: now})
	sum := m.Summary("24h")
	total, _ := sum["total"].(map[string]any)
	if total["total"] != 3 || total["success"] != 2 || total["failed"] != 1 {
		t.Fatalf("total=%v", total)
	}
	if r, _ := total["success_rate"].(float64); r != 2.0/3 {
		t.Fatalf("rate=%v", r)
	}
	byModel, _ := total["by_model"].(map[string]int)
	if byModel["gpt-image-2"] != 3 {
		t.Fatalf("by_model=%v", byModel)
	}
	byEp, _ := total["by_endpoint"].(map[string]int)
	if byEp["/v1/images/generations"] != 3 {
		t.Fatalf("by_endpoint=%v", byEp)
	}
	byErr, _ := total["by_error_code"].(map[string]int)
	if byErr["image_quota_exhausted"] != 1 {
		t.Fatalf("by_error_code=%v", byErr)
	}
	avg, _ := total["model_avg_times"].(map[string]float64)
	// (9000+11000+500)/3：失败调用的耗时同样计入（与 Python 一致）
	if got := avg["gpt-image-2"]; got < 6833 || got > 6834 {
		t.Fatalf("avg time=%v want ~6833", got)
	}
	// rate_limited 识别
	m.Record(CallEvent{Status: "error", ErrorCode: "upstream_rate_limited", At: now})
	if sum2 := m.Summary("24h"); sum2["total"].(map[string]any)["rate_limited"] != 1 {
		t.Fatalf("rate_limited missing: %v", sum2["total"])
	}
}

// TestSummaryRanges P1.7：24h→24 点小时序列，7d/30d→按天。
func TestSummaryRanges(t *testing.T) {
	m := New()
	m.Record(CallEvent{Status: "success", Model: "gpt-image-2"})
	for _, rng := range []string{"24h", "7d", "30d"} {
		sum := m.Summary(rng)
		labels, _ := sum["labels"].([]string)
		series, _ := sum["series"].([]map[string]any)
		want := 24
		if rng == "7d" {
			want = 7
		} else if rng == "30d" {
			want = 30
		}
		if len(labels) != want || len(series) != want {
			t.Fatalf("%s: labels=%d series=%d want %d", rng, len(labels), len(series), want)
		}
	}
	// 未知 range 回退 24h
	if got := len(m.Summary("bogus")["labels"].([]string)); got != 24 {
		t.Fatalf("bogus range labels=%d", got)
	}
}

// TestPersistenceAndRestart P1.7：flush 落盘 + 重启恢复 + 保留期裁剪。
func TestPersistenceAndRestart(t *testing.T) {
	dir := t.TempDir()
	m := NewWithDir(dir)
	m.Record(CallEvent{Status: "success", Model: "gpt-image-2"})
	if err := m.Flush(); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(dir, fileName)); err != nil {
		t.Fatalf("metrics file missing: %v", err)
	}
	// 重启恢复
	m2 := NewWithDir(dir)
	if sum := m2.Summary("24h"); sum["total"].(map[string]any)["total"] != 1 {
		t.Fatalf("restart lost data: %v", sum["total"])
	}
	// 保留期裁剪：注入 40 天前旧桶，flush 后应被删
	old := time.Now().AddDate(0, 0, -40).Format("2006-01-02")
	m2.mu.Lock()
	m2.days[old] = newBucket()
	m2.dirty = true
	m2.mu.Unlock()
	if err := m2.Flush(); err != nil {
		t.Fatal(err)
	}
	m3 := NewWithDir(dir)
	for _, d := range m3.Days() {
		if d == old {
			t.Fatalf("retention failed, old day %s kept", old)
		}
	}
}

// TestDayHourDualBucket P1.7：日桶与小时桶双记。
func TestDayHourDualBucket(t *testing.T) {
	m := New()
	at := time.Date(2026, 3, 5, 14, 30, 0, 0, time.UTC)
	m.Record(CallEvent{Status: "success", At: at})
	// UTC 14:30 → Beijing 22:30（同日）
	m.mu.Lock()
	day := m.days["2026-03-05"]
	m.mu.Unlock()
	if day == nil || day.Total != 1 {
		t.Fatalf("day bucket missing: %v", m.Days())
	}
	if day.Hours == nil || day.Hours["22"] == nil || day.Hours["22"].Total != 1 {
		t.Fatalf("hour bucket missing: %+v", day.Hours)
	}
}
