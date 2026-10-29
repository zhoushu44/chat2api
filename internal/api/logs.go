package api

import (
	"net/http"
	"strconv"
	"strings"
	"time"

	"chatgpt2api/internal/logsvc"

	"github.com/gin-gonic/gin"
)

// LogsHandler 真实调用日志查询：从 logsvc 的内存+JSONL 记录返回，
// 不再让 /api/logs 落入 SPA 静态页。
type LogsHandler struct {
	Svc     *logsvc.Service
	Runtime *logsvc.RuntimeService
}

func (h *LogsHandler) Register(r *gin.RouterGroup) {
	r.GET("/logs", h.List)
	r.POST("/logs/delete", h.Delete)
	r.GET("/runtime-logs", h.ListRuntime)
}

func (h *LogsHandler) List(c *gin.Context) {
	if h.Svc == nil {
		c.JSON(http.StatusOK, gin.H{"items": []any{}, "total": 0, "limit": 0, "offset": 0, "has_more": false})
		return
	}
	limit := clampInt(c.DefaultQuery("limit", "500"), 1, 20000)
	offset := clampInt(c.DefaultQuery("offset", "0"), 0, 10000000)
	search := strings.ToLower(strings.TrimSpace(c.Query("search")))
	statusFilter := strings.ToLower(strings.TrimSpace(c.Query("status")))
	modelFilter := strings.TrimSpace(c.Query("model"))
	accountFilter := strings.TrimSpace(c.Query("account"))
	typeFilter := strings.TrimSpace(c.Query("type"))

	calls := h.Svc.List()
	items := make([]gin.H, 0, len(calls))
	stats := gin.H{"total": 0, "success": 0, "failed": 0, "limited": 0, "image": 0, "text_reply": 0}
	facets := gin.H{"statuses": map[string]int{}, "endpoints": map[string]int{}, "models": map[string]int{}, "accounts": map[string]int{}}
	for i := len(calls) - 1; i >= 0; i-- {
		call := calls[i]
		status := call.Status
		account := ""
		code := ""
		if len(call.Attempts) > 0 {
			account = call.Attempts[len(call.Attempts)-1].AccountID
			code = call.Attempts[len(call.Attempts)-1].Code
		}
		endpoint := "/v1/images/generations"
		if typeFilter == "system" {
			endpoint = "system"
		}
		stats["total"] = stats["total"].(int) + 1
		facets["statuses"].(map[string]int)[status]++
		facets["endpoints"].(map[string]int)[endpoint]++
		facets["models"].(map[string]int)[call.Model]++
		facets["accounts"].(map[string]int)[account]++
		if status == "success" {
			stats["success"] = stats["success"].(int) + 1
		} else {
			stats["failed"] = stats["failed"].(int) + 1
		}
		if strings.Contains(strings.ToLower(code), "limit") || strings.Contains(strings.ToLower(code), "quota") {
			stats["limited"] = stats["limited"].(int) + 1
		}
		stats["image"] = stats["image"].(int) + 1
		if code == "upstream_text_reply" {
			stats["text_reply"] = stats["text_reply"].(int) + 1
		}
		if statusFilter != "" && status != statusFilter {
			continue
		}
		if modelFilter != "" && call.Model != modelFilter {
			continue
		}
		if accountFilter != "" && account != accountFilter {
			continue
		}
		if search != "" && !strings.Contains(strings.ToLower(call.Prompt+" "+call.Model+" "+account+" "+code), search) {
			continue
		}
		items = append(items, gin.H{
			"id": call.ID, "time": call.CreatedAt, "type": "image",
			"summary": call.Model + " 调用" + statusText(status),
			"detail": gin.H{
				"status": status, "model": call.Model, "endpoint": endpoint,
				"account_email": account, "request_text": call.Prompt,
				"error_code": code, "error": errorText(status, code),
				"started_at": call.CreatedAt, "ended_at": call.CreatedAt,
			},
		})
	}
	total := len(items)
	start := minInt(offset, total)
	end := minInt(start+limit, total)
	c.JSON(http.StatusOK, gin.H{
		"items": items[start:end], "total": total, "limit": limit, "offset": offset,
		"has_more": end < total, "facets": facets, "stats": stats,
	})
}

func (h *LogsHandler) Delete(c *gin.Context) {
	// 当前日志服务是只追加 JSONL；不假装支持物理删除。
	// 返回明确错误，避免前端显示「已删除」但重启又出现。
	c.JSON(http.StatusNotImplemented, gin.H{"error": "当前 JSONL 日志不支持物理删除"})
}

func (h *LogsHandler) ListRuntime(c *gin.Context) {
	limit := clampInt(c.DefaultQuery("limit", "300"), 1, 2000)
	search := strings.ToLower(strings.TrimSpace(c.Query("search")))
	items := make([]gin.H, 0)
	if h.Runtime != nil {
		logs := h.Runtime.List()
		for i := len(logs) - 1; i >= 0 && len(items) < limit; i-- {
			entry := logs[i]
			if search != "" && !strings.Contains(strings.ToLower(entry.Message), search) {
				continue
			}
			items = append(items, gin.H{"time": entry.At, "level": "info", "message": entry.Message, "source": "memory"})
		}
	}
	c.JSON(http.StatusOK, gin.H{
		"items": items, "total": len(items), "limit": limit,
		"sources": gin.H{"memory": h.Runtime != nil, "files": []string{}},
	})
}

func statusText(status string) string {
	if status == "success" {
		return "成功"
	}
	return "失败"
}

func errorText(status, code string) string {
	if status == "success" {
		return ""
	}
	return code
}

func clampInt(raw string, min, max int) int {
	v, err := strconv.Atoi(raw)
	if err != nil {
		v = min
	}
	if v < min {
		v = min
	}
	if v > max {
		v = max
	}
	return v
}

func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}

var _ = time.Now
