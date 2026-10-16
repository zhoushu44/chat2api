package register

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// Client RegiForge 任务桥接客户端（对等 Python register_service 的 _http_json + REGIFORGE_*）。
//
// 容器内互访（regiforge / 127.0.0.1）必须旁路代理：Transport.Proxy=nil，
// 避免 HTTP(S)_PROXY 环境变量把内网请求劫持转发到外网代理
// （对等 Python `_OPENER = build_opener(ProxyHandler({}))`）。
type Client struct {
	BaseURL   string
	ProjectID string
	EmailID   string
	ProxyID   string
	CaptchaID string
	SMSID     string
	HTTP      *http.Client
}

// NewClientFromEnv 从环境变量构造，默认值对齐 Python register_service.py:46-52。
func NewClientFromEnv() *Client {
	return &Client{
		BaseURL:   strings.TrimRight(envOr("REGIFORGE_BASE_URL", "http://regiforge:8787"), "/"),
		ProjectID: envOr("REGIFORGE_PROJECT_ID", "chatgpt_register"),
		EmailID:   envOr("REGIFORGE_EMAIL_ID", "mailnest"),
		ProxyID:   envOr("REGIFORGE_PROXY_ID", "wary"),
		CaptchaID: envOr("REGIFORGE_CAPTCHA_ID", "turnstile.browser_manual"),
		SMSID:     envOr("REGIFORGE_SMS_ID", ""),
		HTTP: &http.Client{
			Timeout:   60 * time.Second,
			Transport: &http.Transport{Proxy: nil},
		},
	}
}

// CreateTask 创建 RegiForge 注册任务（payload 对等 Python _start_task_locked）。
// 返回 task_id；非 200 / 无 task_id / 解码失败均返回 error。
func (c *Client) CreateTask(plan, threads int) (string, error) {
	payload := map[string]any{
		"project_id":  c.ProjectID,
		"captcha_id":  c.CaptchaID,
		"email_id":    c.EmailID,
		"proxy_id":    c.ProxyID,
		"sms_id":      c.SMSID,
		"total":       plan,
		"start":       1,
		"concurrency": threads,
		"stagger":     0,
		"headless":    false,
	}
	body, _ := json.Marshal(payload)
	req, err := http.NewRequest(http.MethodPost, c.BaseURL+"/api/tasks", bytes.NewReader(body))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json")
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		raw, _ := io.ReadAll(io.LimitReader(resp.Body, 1024))
		return "", fmt.Errorf("regiforge create task: HTTP %d: %s", resp.StatusCode, strings.TrimSpace(string(raw)))
	}
	var out struct {
		TaskID string `json:"task_id"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return "", err
	}
	if out.TaskID == "" {
		return "", fmt.Errorf("regiforge create task: empty task_id")
	}
	return out.TaskID, nil
}

// TaskStatus RegiForge 任务状态（对等 Python _poll 解析的 resp 字段）。
type TaskStatus struct {
	Done   int    `json:"done"`
	OK     int    `json:"ok"`
	Failed int    `json:"failed"`
	Total  int    `json:"total"`
	State  string `json:"state"`
}

// Finished 结束态（对等 Python `state in {"done","failed","stopped","cancelled"}`）。
func (s TaskStatus) Finished() bool {
	switch s.State {
	case "done", "failed", "stopped", "cancelled":
		return true
	}
	return false
}

// Running 运行中数量（对等 Python `0 if finished else total-done`，下限 0）。
func (s TaskStatus) Running() int {
	if s.Finished() {
		return 0
	}
	if n := s.Total - s.Done; n > 0 {
		return n
	}
	return 0
}

// SuccessRate 成功率（对等 Python `round(ok*100/max(1,ok+failed),1)`）。
func (s TaskStatus) SuccessRate() float64 {
	if s.OK+s.Failed == 0 {
		return 0
	}
	return float64(s.OK*100) / float64(s.OK+s.Failed)
}

// doJSON 通用 JSON 请求，非 200 返回 error（含前 1KB 响应体便于排查）。
func (c *Client) doJSON(method, path string, payload any, timeout time.Duration, out any) error {
	var body io.Reader
	if payload != nil {
		b, _ := json.Marshal(payload)
		body = bytes.NewReader(b)
	}
	req, err := http.NewRequest(method, c.BaseURL+path, body)
	if err != nil {
		return err
	}
	req.Header.Set("Accept", "application/json")
	if payload != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	hc := *c.HTTP
	hc.Timeout = timeout
	resp, err := hc.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		raw, _ := io.ReadAll(io.LimitReader(resp.Body, 1024))
		return fmt.Errorf("regiforge %s %s: HTTP %d: %s", method, path, resp.StatusCode, strings.TrimSpace(string(raw)))
	}
	if out == nil {
		return nil
	}
	return json.NewDecoder(resp.Body).Decode(out)
}

// GetTask 查询任务状态（对等 Python `_poll` 的 `GET /api/tasks/{id}`）。
func (c *Client) GetTask(id string) (TaskStatus, error) {
	var st TaskStatus
	err := c.doJSON(http.MethodGet, "/api/tasks/"+id, nil, 20*time.Second, &st)
	return st, err
}

// GetLogs 拉取任务日志行（对等 Python `GET /api/tasks/{id}/logs` 的 lines）。
func (c *Client) GetLogs(id string) ([]string, error) {
	var out struct {
		Lines []string `json:"lines"`
	}
	if err := c.doJSON(http.MethodGet, "/api/tasks/"+id+"/logs", nil, 20*time.Second, &out); err != nil {
		return nil, err
	}
	return out.Lines, nil
}

// StopTask 停止任务（对等 Python `POST /api/tasks/{id}/stop`）。
func (c *Client) StopTask(id string) error {
	return c.doJSON(http.MethodPost, "/api/tasks/"+id+"/stop", map[string]any{}, 20*time.Second, nil)
}
