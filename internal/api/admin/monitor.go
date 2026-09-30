package admin

import (
	"net/http"
	"strconv"
	"time"

	"chatgpt2api/internal/monitor"
	"chatgpt2api/internal/monitor/metrics"

	"github.com/gin-gonic/gin"
)

// MonitorHandler 实时监控页（Monitor）+ 公开 uptime。
// 前端契约：
//
//	GET /api/monitor/realtime → {summary,active[],recent[],slow[],events[],
//	                             threadpool{tokens},window{completed,completed_capacity},...}
//	GET /public/uptime?days=N → {updated_at,services{<key>:{name,status,uptime,total,success,heartbeats[]}}}
type MonitorHandler struct {
	Mon     *monitor.Service
	Metrics *metrics.Metrics
}

func (h *MonitorHandler) Register(r *gin.RouterGroup) {
	r.GET("/monitor/realtime", h.Realtime)
}

// RegisterPublic 公开路由（无 /api 前缀、无鉴权）。
func (h *MonitorHandler) RegisterPublic(r *gin.Engine) {
	r.GET("/public/uptime", h.Uptime)
}

// Realtime 实时监控快照。
func (h *MonitorHandler) Realtime(c *gin.Context) {
	events := []gin.H{}
	if h.Mon != nil {
		for _, e := range h.Mon.Events() {
			events = append(events, gin.H{
				"time":    e.At.Format("2006-01-02 15:04:05"),
				"task_id": e.TaskID,
				"stage":   e.Stage,
				"detail":  e.Detail,
				"message": e.Stage + " " + e.Detail,
			})
		}
	}
	if len(events) > 30 {
		events = events[len(events)-30:]
	}

	summary := map[string]any{}
	total, success, failed, rateLimited := 0, 0, 0, 0
	if h.Metrics != nil {
		summary = h.Metrics.Summary("24h")
		if s, ok := summary["total"].(map[string]any); ok {
			total = intOf(s["total"])
			success = intOf(s["success"])
			failed = intOf(s["failed"])
			rateLimited = intOf(s["rate_limited"])
		}
	}
	successRate := 0.0
	if total > 0 {
		successRate = float64(success) / float64(total)
	}

	c.JSON(http.StatusOK, gin.H{
		"summary": gin.H{
			"total":        total,
			"success":      success,
			"failed":       failed,
			"rate_limited": rateLimited,
			"success_rate": successRate,
			"time_range":   "24h",
		},
		"active":          []gin.H{},
		"recent":          []gin.H{},
		"slow":            []gin.H{},
		"events":          events,
		"threadpool":      gin.H{"tokens": "-"},
		"window":          gin.H{"completed": success, "completed_capacity": total},
		"active_count":    0,
		"completed":       success,
		"failed":          failed,
		"success_rate":    successRate,
		"avg_duration_ms": 0,
		"p95_duration_ms": 0,
		"metric_p95":      gin.H{},
		"slow_counts":     gin.H{},
		"bottleneck":      gin.H{"label": "-", "value_ms": 0},
		"perf":            gin.H{},
		"generated_at":    time.Now().Format("2006-01-02 15:04:05"),
	})
}

// Uptime GET /public/uptime?days=N
func (h *MonitorHandler) Uptime(c *gin.Context) {
	days := parseIntDefault(c.Query("days"), 90)
	if days < 1 {
		days = 90
	}

	var heartbeats []gin.H
	uptimePct := 100.0
	total, success := 0, 0

	if h.Metrics != nil {
		timeRange := "30d"
		if days <= 7 {
			timeRange = "7d"
		}
		summary := h.Metrics.Summary(timeRange)
		labels, _ := summary["labels"].([]string)
		series, _ := summary["series"].([]map[string]any)
		for _, s := range series {
			t := intOf(s["total"])
			ok := intOf(s["success"])
			total += t
			success += ok
			var label string
			if len(labels) > 0 {
				label = labels[0]
				labels = labels[1:]
			}
			level := "up"
			if t > 0 && ok == 0 {
				level = "down"
			} else if t > 0 && float64(ok)/float64(t) < 0.9 {
				level = "warn"
			}
			heartbeats = append(heartbeats, gin.H{
				"time":        label,
				"success":     t == 0 || ok > 0,
				"latency_ms":  nil,
				"status_code": nil,
				"level":       level,
			})
		}
	}
	if total > 0 {
		uptimePct = float64(success) / float64(total) * 100
	}
	status := "up"
	if total > 0 && success == 0 {
		status = "down"
	} else if uptimePct < 90 {
		status = "warn"
	}
	// 心跳条最多展示 60 条（前端 Y=60）
	if len(heartbeats) > 60 {
		heartbeats = heartbeats[len(heartbeats)-60:]
	}

	c.JSON(http.StatusOK, gin.H{
		"updated_at": time.Now().Format("2006-01-02 15:04:05"),
		"services": gin.H{
			"chatgpt2api": gin.H{
				"name":       "chatgpt2api",
				"status":     status,
				"uptime":     round2(uptimePct),
				"total":      total,
				"success":    success,
				"heartbeats": heartbeats,
			},
		},
	})
}

func intOf(v any) int {
	switch n := v.(type) {
	case int:
		return n
	case int64:
		return int(n)
	case float64:
		return int(n)
	case string:
		f, err := strconv.ParseFloat(n, 64)
		if err != nil {
			return 0
		}
		return int(f)
	}
	return 0
}

func round2(f float64) float64 {
	return float64(int(f*100+0.5)) / 100
}
