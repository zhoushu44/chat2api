package backend

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	fhttp "github.com/bogdanfinn/fhttp"
)

// BackendTask 对等后端任务结构
type BackendTask struct {
	ID             string `json:"id"`
	ConversationID string `json:"conversation_id"`
	Status         string `json:"status"`
	Error          string `json:"error"`
}

// QueryBackendTasks 查询后端任务，对等 _query_backend_tasks
func (b *Backend) QueryBackendTasks(ctx context.Context, conversationID string) ([]BackendTask, error) {
	path := "/backend-api/tasks"
	if conversationID != "" {
		path += "?conversation_id=" + conversationID
	}
	headers := b.RequestHeaders(path, map[string]string{"Accept": "application/json"})
	reqCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	resp, body, err := b.doJSONRequest(reqCtx, fhttp.MethodGet, b.BaseURL+path, headers, nil)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("tasks query %d: %s", resp.StatusCode, diagnosticExcerpt(string(body), 500))
	}
	var out struct {
		Tasks []BackendTask `json:"tasks"`
		Data  []BackendTask `json:"data"`
	}
	_ = json.Unmarshal(body, &out)
	if len(out.Tasks) > 0 {
		return out.Tasks, nil
	}
	if len(out.Data) > 0 {
		return out.Data, nil
	}
	// 尝试直接数组
	var arr []BackendTask
	if err := json.Unmarshal(body, &arr); err == nil {
		return arr, nil
	}
	return nil, nil
}

// ImageTaskDiagnostics 对等 image_task_diagnostics
func (b *Backend) ImageTaskDiagnostics(task BackendTask) (string, map[string]any) {
	meta := map[string]any{
		"task_id": task.ID,
		"status":  task.Status,
	}
	errMsg := task.Error
	if errMsg == "" {
		errMsg = task.Status
	}
	// 简单分类：若包含特定关键字
	if strings.Contains(strings.ToLower(errMsg), "quota") {
		meta["code"] = "image_quota_exhausted"
	}
	return errMsg, meta
}
