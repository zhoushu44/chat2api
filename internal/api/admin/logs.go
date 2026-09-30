package admin

import (
	"fmt"
	"net/http"
	"strconv"
	"strings"

	"chatgpt2api/internal/logsvc"

	"github.com/gin-gonic/gin"
)

// LogsHandler 日志页（Logs）：调用日志 + 运行日志。
// 前端契约（web_dist/assets/Logs-*.js）：
//
//	GET  /api/logs?limit&offset&level&search&status&model&endpoint
//	     → {items,total,limit,offset,has_more,facets{statuses,endpoints,models,accounts},
//	        stats{total,success,failed,limited,image,text_reply}}
//	     每个 item: {id,time,type,summary,detail{endpoint,model,status,error,error_code,
//	                conversation_id,account_email,request_text}}
//	GET  /api/runtime-logs?limit → {items,total,limit,sources{memory,files}}
//	POST /api/logs/delete {ids}
type LogsHandler struct {
	LogSvc  *logsvc.Service
	Runtime *logsvc.RuntimeService
	DataDir string
}

func (h *LogsHandler) Register(r *gin.RouterGroup) {
	r.GET("/logs", h.List)
	r.GET("/runtime-logs", h.ListRuntime)
	r.POST("/logs/delete", h.Delete)
}

// List 调用日志（同端点同时服务 Logs 页的 list 与 listSystem）。
func (h *LogsHandler) List(c *gin.Context) {
	limit := parseIntDefault(c.Query("limit"), 500)
	if limit < 1 {
		limit = 500
	}
	if limit > 20000 {
		limit = 20000
	}
	offset := parseIntDefault(c.Query("offset"), 0)
	if offset < 0 {
		offset = 0
	}
	levelFilter := strings.ToUpper(strings.TrimSpace(c.Query("level")))
	searchFilter := strings.ToLower(strings.TrimSpace(c.Query("search")))
	statusFilter := strings.ToLower(strings.TrimSpace(c.Query("status")))
	modelFilter := strings.TrimSpace(c.Query("model"))
	endpointFilter := strings.TrimSpace(c.Query("endpoint"))

	var src []*logsvc.LoggedCall
	if h.LogSvc != nil {
		src = h.LogSvc.List()
	}

	facets := gin.H{
		"statuses":  map[string]int{},
		"endpoints": map[string]int{},
		"models":    map[string]int{},
		"accounts":  map[string]int{},
	}
	fStatuses := facets["statuses"].(map[string]int)
	fEndpoints := facets["endpoints"].(map[string]int)
	fModels := facets["models"].(map[string]int)
	fAccounts := facets["accounts"].(map[string]int)

	all := make([]gin.H, 0, len(src))
	// 倒序：最新在前
	for i := len(src) - 1; i >= 0; i-- {
		lc := src[i]
		errCode := ""
		accountID := ""
		if len(lc.Attempts) > 0 {
			errCode = lc.Attempts[0].Code
			accountID = lc.Attempts[0].AccountID
		}
		endpoint := "/v1/images/generations"
		if lc.Model == "" {
			endpoint = ""
		}
		status := lc.Status
		if status == "" {
			status = "success"
		}
		level := "INFO"
		switch {
		case status == "failed" || errCode != "":
			level = "ERROR"
		case strings.Contains(strings.ToLower(status), "limit"):
			level = "WARNING"
		}
		item := gin.H{
			"id":      lc.ID,
			"time":    lc.CreatedAt.Format("2006-01-02 15:04:05"),
			"type":    "image",
			"level":   level,
			"summary": strings.TrimSpace(lc.Model + " " + status),
			"detail": gin.H{
				"endpoint":        endpoint,
				"model":           lc.Model,
				"status":          status,
				"error":           errCode,
				"error_code":      errCode,
				"conversation_id": lc.ID,
				"account_email":   accountID,
				"request_text":    lc.Prompt,
			},
		}
		all = append(all, item)
		fStatuses[status]++
		if endpoint != "" {
			fEndpoints[endpoint]++
		}
		if lc.Model != "" {
			fModels[lc.Model]++
		}
		if accountID != "" {
			fAccounts[accountID]++
		}
	}

	// 过滤（level/search/status/model/endpoint）
	filtered := make([]gin.H, 0, len(all))
	statsTotal, statsSuccess, statsFailed, statsLimited, statsImage := 0, 0, 0, 0, 0
	for _, it := range all {
		detail := it["detail"].(gin.H)
		if levelFilter != "" && it["level"] != levelFilter {
			continue
		}
		if statusFilter != "" && !strings.EqualFold(toStr(detail["status"]), statusFilter) {
			continue
		}
		if modelFilter != "" && toStr(detail["model"]) != modelFilter {
			continue
		}
		if endpointFilter != "" && toStr(detail["endpoint"]) != endpointFilter {
			continue
		}
		if searchFilter != "" {
			hay := strings.ToLower(strings.Join([]string{
				toStr(it["id"]), toStr(it["summary"]), toStr(it["time"]),
				toStr(detail["model"]), toStr(detail["endpoint"]),
				toStr(detail["account_email"]), toStr(detail["error_code"]),
				toStr(detail["request_text"]),
			}, " "))
			if !strings.Contains(hay, searchFilter) {
				continue
			}
		}
		filtered = append(filtered, it)
		statsTotal++
		st := strings.ToLower(toStr(detail["status"]))
		switch {
		case st == "success" || st == "":
			statsSuccess++
		default:
			statsFailed++
		}
		if strings.Contains(st, "limit") {
			statsLimited++
		}
		if strings.HasPrefix(toStr(detail["endpoint"]), "/v1/images") {
			statsImage++
		}
	}

	total := len(filtered)
	start := offset
	if start > total {
		start = total
	}
	end := start + limit
	if end > total {
		end = total
	}
	pageItems := filtered[start:end]

	c.JSON(http.StatusOK, gin.H{
		"items":    pageItems,
		"total":    total,
		"limit":    limit,
		"offset":   offset,
		"has_more": end < total,
		"facets":   facets,
		"stats": gin.H{
			"total":      statsTotal,
			"success":    statsSuccess,
			"failed":     statsFailed,
			"limited":    statsLimited,
			"image":      statsImage,
			"text_reply": 0,
		},
	})
}

// ListRuntime 运行日志（进程内环形缓冲）。
func (h *LogsHandler) ListRuntime(c *gin.Context) {
	limit := parseIntDefault(c.Query("limit"), 300)
	if limit < 1 {
		limit = 300
	}
	if limit > 2000 {
		limit = 2000
	}
	var logs []logsvc.RuntimeLog
	if h.Runtime != nil {
		logs = h.Runtime.List()
	}
	items := make([]gin.H, 0, len(logs))
	for i := len(logs) - 1; i >= 0; i-- {
		l := logs[i]
		items = append(items, gin.H{
			"key":  strconv.FormatInt(l.At.UnixNano(), 10),
			"time": l.At.Format("2006-01-02 15:04:05"),
			"text": l.Message,
			"line": l.Message,
		})
		if len(items) >= limit {
			break
		}
	}
	c.JSON(http.StatusOK, gin.H{
		"items": items,
		"total": len(items),
		"limit": limit,
		"sources": gin.H{
			"memory": true,
			"files":  []string{},
		},
	})
}

// Delete 删除日志（环形缓冲不支持按条删除，前端本地移除即可）。
func (h *LogsHandler) Delete(c *gin.Context) {
	var body struct {
		IDs []string `json:"ids"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"ok": false, "error": gin.H{"message": "invalid body"}})
		return
	}
	c.JSON(http.StatusOK, gin.H{"ok": true, "deleted": len(body.IDs)})
}

func parseIntDefault(s string, def int) int {
	if strings.TrimSpace(s) == "" {
		return def
	}
	n, err := strconv.Atoi(strings.TrimSpace(s))
	if err != nil {
		return def
	}
	return n
}

func toStr(v any) string {
	if v == nil {
		return ""
	}
	if s, ok := v.(string); ok {
		return s
	}
	return fmt.Sprint(v)
}
