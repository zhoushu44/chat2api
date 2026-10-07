package oauth

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	fhttp "github.com/bogdanfinn/fhttp"
	tls_client "github.com/bogdanfinn/tls-client"
)

// auth.openai.com 的 sentinel 校验必须用 OpenAI 真 sdk.js 求解：
// 本地伪造的 requirements token 能骗过表面校验，但 password/verify 等服务端深校验会拒
// （线上表现为 401 invalid_username_or_password），导致协议恢复永远失败。
//
// 落地方案：复用容器内已有的 regiforge sentinel 资产（node + 真 sdk.js），
// 两遍流程：requirements → request_p；POST /sentinel/req 拿 challenge；solve → token。
// 契约与 regiforge/projects/chatgpt_register/steps/_sentinel_quickjs.py 一致。
const (
	sentinelVersion = "20260219f9f6"
	sentinelSDKURL  = "https://sentinel.openai.com/sentinel/" + sentinelVersion + "/sdk.js"
	sentinelReqURL  = "https://sentinel.openai.com/backend-api/sentinel/req"
	sentinelFlow    = "authorize_continue"

	defaultSentinelScript = "/opt/regiforge/projects/chatgpt_register/steps/_openai_sentinel_quickjs.js"
	defaultSentinelSDK    = "/opt/regiforge/projects/chatgpt_register/steps/sentinel_vm/sdk.js"
)

// sentinelSolver 为 auth.openai.com 请求生成 sentinel 头（真 sdk.js 求解）。
type sentinelSolver interface {
	Solve(ctx context.Context, deviceID, flow string) (token, soToken string, err error)
}

// newSentinelSolver 用容器内已有的 node + 真 sdk.js 资产构造求解器。
func newSentinelSolver(http tls_client.HttpClient, userAgent string, log func(string)) sentinelSolver {
	return &nodeSentinelSolver{
		http:   http,
		ua:     userAgent,
		node:   envOr("OPENAI_SENTINEL_NODE_PATH", "node"),
		script: envOr("CHAT2API_SENTINEL_SCRIPT", defaultSentinelScript),
		log:    log,
	}
}

func envOr(key, def string) string {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		return v
	}
	return def
}

type nodeSentinelSolver struct {
	http   tls_client.HttpClient
	ua     string
	node   string
	script string
	log    func(string)
}

func (s *nodeSentinelSolver) logf(format string, args ...any) {
	if s.log != nil {
		s.log(fmt.Sprintf(format, args...))
	}
}

// Solve 走完整两遍流程，返回完整 openai-sentinel-token 头值（JSON 串）与可选 so token。
func (s *nodeSentinelSolver) Solve(ctx context.Context, deviceID, flow string) (string, string, error) {
	if flow == "" {
		flow = sentinelFlow
	}
	sdk, err := s.ensureSDK(ctx)
	if err != nil {
		return "", "", err
	}
	env := s.envPayload(deviceID)

	reqOut, err := s.runNode(ctx, sdk, mergeMaps(env, map[string]any{
		"action": "requirements",
		"flow":   flow,
	}))
	if err != nil {
		return "", "", err
	}
	requestP, _ := reqOut["request_p"].(string)
	requestP = strings.TrimSpace(requestP)
	if requestP == "" {
		return "", "", fmt.Errorf("sentinel: requirements 未返回 request_p")
	}

	challenge, err := s.fetchChallenge(ctx, deviceID, flow, requestP)
	if err != nil {
		return "", "", err
	}
	if c, _ := challenge["token"].(string); strings.TrimSpace(c) == "" {
		return "", "", fmt.Errorf("sentinel: challenge token 为空")
	}

	solved, err := s.runNode(ctx, sdk, mergeMaps(env, map[string]any{
		"action":               "solve",
		"flow":                 flow,
		"request_p":            requestP,
		"challenge":            challenge,
		"behavior_duration_ms": 4200,
	}))
	if err != nil {
		return "", "", err
	}
	token, _ := solved["token"].(string)
	token = strings.TrimSpace(token)
	soToken, _ := solved["so_token"].(string)
	soToken = strings.TrimSpace(soToken)

	// 服务端在 challenge 里说了算 SO token 是否必需；求解失败宁可放弃也不发残缺头（避免封号）。
	if token == "" {
		return "", "", fmt.Errorf("sentinel: SDK token 为空（放弃以免封号）")
	}
	if challengeSORequired(challenge) && soToken == "" {
		return "", "", fmt.Errorf("sentinel: 服务端要求 SO token 但求解为空（放弃以免封号）")
	}
	s.logf("sentinel ok (flow=%s len=%d so=%v)", flow, len(token), soToken != "")
	return token, soToken, nil
}

// challengeSORequired 判断 challenge 是否要求 session observer token。
func challengeSORequired(challenge map[string]any) bool {
	so, _ := challenge["so"].(map[string]any)
	if so == nil {
		return false
	}
	required, _ := so["required"].(bool)
	return required
}

// envPayload 构造喂给 sdk.js 的浏览器指纹（与 loginUA 保持 Windows Chrome 一致）。
func (s *nodeSentinelSolver) envPayload(deviceID string) map[string]any {
	return map[string]any{
		"device_id":            deviceID,
		"user_agent":           s.ua,
		"platform":             "Win32",
		"vendor":               "Google Inc.",
		"hardware_concurrency": 8,
		"language":             "en-US",
		"languages":            []string{"en-US", "en"},
		"screen_width":         1920,
		"screen_height":        1080,
		"timezone":             "UTC",
	}
}

// runNode 起 node 跑真 sdk.js 适配层，stdin 传 JSON、stdout 收 JSON。
func (s *nodeSentinelSolver) runNode(ctx context.Context, sdk string, payload map[string]any) (map[string]any, error) {
	if _, err := os.Stat(s.script); err != nil {
		return nil, fmt.Errorf("sentinel 脚本不存在: %s", s.script)
	}
	body, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}
	runCtx, cancel := context.WithTimeout(ctx, 90*time.Second)
	defer cancel()
	cmd := exec.CommandContext(runCtx, s.node, s.script)
	cmd.Stdin = bytes.NewReader(body)
	cmd.Env = append(os.Environ(), "OPENAI_SENTINEL_SDK_FILE="+sdk)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		return nil, fmt.Errorf("sentinel node: %w (%s)", err, cut(strings.TrimSpace(stderr.String()), 300))
	}
	var out map[string]any
	if err := json.Unmarshal(stdout.Bytes(), &out); err != nil {
		return nil, fmt.Errorf("sentinel node 输出解析: %w (%s)", err, cut(strings.TrimSpace(stdout.String()), 200))
	}
	return out, nil
}

// fetchChallenge POST /backend-api/sentinel/req 换取 challenge（用同一 TLS 指纹客户端 + 出口）。
func (s *nodeSentinelSolver) fetchChallenge(ctx context.Context, deviceID, flow, requestP string) (map[string]any, error) {
	body, _ := json.Marshal(map[string]string{"p": requestP, "id": deviceID, "flow": flow})
	reqCtx, cancel := context.WithTimeout(ctx, 40*time.Second)
	defer cancel()
	req, err := fhttp.NewRequestWithContext(reqCtx, "POST", sentinelReqURL, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	h := fhttp.Header{}
	h.Set("User-Agent", s.ua)
	h.Set("Origin", "https://sentinel.openai.com")
	h.Set("Referer", "https://sentinel.openai.com/backend-api/sentinel/frame.html?sv="+sentinelVersion)
	h.Set("Content-Type", "text/plain;charset=UTF-8")
	h.Set("Accept", "*/*")
	h.Set("Accept-Language", "en-US,en;q=0.9")
	h.Set("Sec-Fetch-Dest", "empty")
	h.Set("Sec-Fetch-Mode", "cors")
	h.Set("Sec-Fetch-Site", "same-origin")
	req.Header = h
	resp, err := s.http.Do(req)
	if err != nil {
		return nil, fmt.Errorf("sentinel/req: %w", err)
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("sentinel/req HTTP %d body=%s", resp.StatusCode, cut(string(data), 200))
	}
	var out map[string]any
	if err := json.Unmarshal(data, &out); err != nil {
		return nil, fmt.Errorf("sentinel/req 解析: %w", err)
	}
	return out, nil
}

// ensureSDK 定位真 sdk.js：env 覆盖 → 缓存 → 容器内资产 → 下载缓存。
func (s *nodeSentinelSolver) ensureSDK(ctx context.Context) (string, error) {
	if p := strings.TrimSpace(os.Getenv("OPENAI_SENTINEL_SDK_FILE")); p != "" {
		if _, err := os.Stat(p); err == nil {
			return p, nil
		}
	}
	cache := filepath.Join(os.TempDir(), "openai-sentinel-demo", sentinelVersion, "sdk.js")
	if fi, err := os.Stat(cache); err == nil && fi.Size() > 0 {
		return cache, nil
	}
	if fi, err := os.Stat(defaultSentinelSDK); err == nil && fi.Size() > 0 {
		return defaultSentinelSDK, nil
	}
	data, err := s.download(ctx, sentinelSDKURL)
	if err != nil {
		return "", err
	}
	if err := os.MkdirAll(filepath.Dir(cache), 0o755); err != nil {
		return "", err
	}
	if err := os.WriteFile(cache, data, 0o644); err != nil {
		return "", err
	}
	return cache, nil
}

func (s *nodeSentinelSolver) download(ctx context.Context, url string) ([]byte, error) {
	reqCtx, cancel := context.WithTimeout(ctx, 60*time.Second)
	defer cancel()
	req, err := fhttp.NewRequestWithContext(reqCtx, "GET", url, nil)
	if err != nil {
		return nil, err
	}
	h := fhttp.Header{}
	h.Set("User-Agent", s.ua)
	h.Set("Accept", "*/*")
	h.Set("Referer", "https://auth.openai.com/")
	h.Set("Sec-Fetch-Dest", "script")
	h.Set("Sec-Fetch-Mode", "no-cors")
	h.Set("Sec-Fetch-Site", "same-site")
	req.Header = h
	resp, err := s.http.Do(req)
	if err != nil {
		return nil, fmt.Errorf("下载 sdk.js: %w", err)
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != 200 || len(data) == 0 {
		return nil, fmt.Errorf("下载 sdk.js HTTP %d", resp.StatusCode)
	}
	return data, nil
}

// mergeMaps 浅合并（后者覆盖前者），用于拼装 node 输入。
func mergeMaps(base, extra map[string]any) map[string]any {
	out := make(map[string]any, len(base)+len(extra))
	for k, v := range base {
		out[k] = v
	}
	for k, v := range extra {
		out[k] = v
	}
	return out
}
