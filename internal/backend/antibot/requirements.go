package antibot

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	fhttp "github.com/bogdanfinn/fhttp"
)

// ChatRequirements 对应 Python ChatRequirements dataclass，但位于 antibot 包以避免循环依赖。
type ChatRequirements struct {
	Token          string
	ProofToken     string
	TurnstileToken string
	SoToken        string
	RawFinalize    map[string]any
}

// httpDoer 最小接口，复刻 backend 的 httpDoer，便于测试注入。
type httpDoer interface {
	Do(req *fhttp.Request) (*fhttp.Response, error)
}

// upstreamStatusErr 带状态码错误：failure.Classify 用 UpstreamStatus() 接口按码归类。
type upstreamStatusErr struct {
	code int
	msg  string
}

func (e *upstreamStatusErr) Error() string            { return e.msg }
func (e *upstreamStatusErr) UpstreamStatus() int      { return e.code }

func statusErrf(code int, format string, args ...any) error {
	return &upstreamStatusErr{code: code, msg: fmt.Sprintf(format, args...)}
}

// Bootstrap 拉取首页并解析 PoW 资源（对等 _bootstrap）。
func Bootstrap(ctx context.Context, client httpDoer, baseURL string, headers http.Header) ([]string, string, error) {
	reqCtx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	req, err := fhttp.NewRequestWithContext(reqCtx, fhttp.MethodGet, strings.TrimRight(baseURL, "/")+"/", nil)
	if err != nil {
		return nil, "", fmt.Errorf("bootstrap build request: %w", err)
	}
	req.Header = fhttp.Header(headers)
	resp, err := client.Do(req)
	if err != nil {
		return nil, "", fmt.Errorf("bootstrap request failed: %w", err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, "", statusErrf(resp.StatusCode, "bootstrap failed: status=%d body=%s", resp.StatusCode, string(body)[:minInt(500, len(body))])
	}
	sources, build := ParsePowResources(string(body))
	if len(sources) == 0 {
		sources = []string{DefaultPowScript}
	}
	return sources, build, nil
}

func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}

// GetChatRequirements 执行 prepare → finalize 两步流（对等 _get_chat_requirements）。
// basePath 为 sentinel 路径前缀：有账号用 /backend-api/sentinel/chat-requirements，
// 匿名用 /backend-anon/sentinel/chat-requirements；空串取默认（auth 前缀）。
// scriptSources/dataBuild 由 Bootstrap 预热获得；p_token 用 BuildLegacyRequirementsToken 生成，
// PoW required 时 proof_token 用 BuildProofToken 计算，turnstile required 时调 SolveTurnstileToken。
func GetChatRequirements(ctx context.Context, client httpDoer, baseURL, basePath, userAgent string, scriptSources []string, dataBuild string, buildHeaders func(path string) http.Header) (*ChatRequirements, error) {
	base := basePath
	if base == "" {
		base = "/backend-api/sentinel/chat-requirements"
	}
	if baseURL == "" {
		baseURL = "https://chatgpt.com"
	}
	preparePath := base + "/prepare"
	pToken := BuildLegacyRequirementsToken(userAgent, scriptSources, dataBuild)
	headers := buildHeaders(preparePath)
	headers.Set("Content-Type", "application/json")
	headers.Set("Accept", "application/json")
	body := mustJSON(map[string]string{"p": pToken})
	resp, respBody, err := doJSON(ctx, client, fhttp.MethodPost, baseURL+preparePath, headers, body)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, statusErrf(resp.StatusCode, "chat_requirements_prepare failed: status=%d body=%s", resp.StatusCode, truncateBody(respBody))
	}
	var prep struct {
		PrepareToken string `json:"prepare_token"`
		Arkose       *struct {
			Required bool `json:"required"`
		} `json:"arkose"`
		ProofOfWork *struct {
			Required   bool   `json:"required"`
			Seed       string `json:"seed"`
			Difficulty string `json:"difficulty"`
		} `json:"proofofwork"`
		Turnstile *struct {
			Required bool   `json:"required"`
			Dx       string `json:"dx"`
		} `json:"turnstile"`
	}
	if err := json.Unmarshal(respBody, &prep); err != nil {
		return nil, fmt.Errorf("parse prepare response: %w body=%s", err, truncateBody(respBody))
	}
	if prep.Arkose != nil && prep.Arkose.Required {
		return nil, fmt.Errorf("chat requirements requires arkose token, which is not implemented")
	}
	proofToken := ""
	if prep.ProofOfWork != nil && prep.ProofOfWork.Required {
		tok, err := BuildProofToken(prep.ProofOfWork.Seed, prep.ProofOfWork.Difficulty, userAgent, scriptSources, dataBuild)
		if err != nil {
			return nil, err
		}
		proofToken = tok
	}
	turnstileToken := ""
	if prep.Turnstile != nil && prep.Turnstile.Required && prep.Turnstile.Dx != "" {
		if tok := SolveTurnstileToken(prep.Turnstile.Dx, pToken); tok != nil {
			turnstileToken = *tok
		}
	}
	finalizePath := base + "/finalize"
	headers2 := buildHeaders(finalizePath)
	headers2.Set("Content-Type", "application/json")
	headers2.Set("Accept", "application/json")
	finBody := mustJSON(map[string]string{
		"prepare_token":   prep.PrepareToken,
		"proof_token":     proofToken,
		"turnstile_token": turnstileToken,
	})
	resp2, respBody2, err := doJSON(ctx, client, fhttp.MethodPost, baseURL+finalizePath, headers2, finBody)
	if err != nil {
		return nil, err
	}
	if resp2.StatusCode < 200 || resp2.StatusCode >= 300 {
		return nil, statusErrf(resp2.StatusCode, "chat_requirements_finalize failed: status=%d body=%s", resp2.StatusCode, truncateBody(respBody2))
	}
	var fin struct {
		Token   string `json:"token"`
		SoToken string `json:"so_token"`
	}
	var raw map[string]any
	_ = json.Unmarshal(respBody2, &raw)
	_ = json.Unmarshal(respBody2, &fin)
	if fin.Token == "" {
		if v, ok := raw["token"].(string); ok {
			fin.Token = v
		}
	}
	if fin.Token == "" {
		return nil, fmt.Errorf("missing chat requirements token: %s", truncateBody(respBody2))
	}
	if fin.SoToken == "" {
		if v, ok := raw["so_token"].(string); ok {
			fin.SoToken = v
		}
	}
	return &ChatRequirements{
		Token:          fin.Token,
		ProofToken:     proofToken,
		TurnstileToken: turnstileToken,
		SoToken:        fin.SoToken,
		RawFinalize:    raw,
	}, nil
}

func doJSON(ctx context.Context, client httpDoer, method, url string, headers http.Header, body []byte) (*fhttp.Response, []byte, error) {
	var r io.Reader
	if body != nil {
		r = bytes.NewReader(body)
	}
	reqCtx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	req, err := fhttp.NewRequestWithContext(reqCtx, method, url, r)
	if err != nil {
		return nil, nil, fmt.Errorf("%s %s build request: %w", method, url, err)
	}
	req.Header = fhttp.Header(headers)
	resp, err := client.Do(req)
	if err != nil {
		return nil, nil, fmt.Errorf("%s %s request failed: %w", method, url, err)
	}
	defer resp.Body.Close()
	b, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, nil, fmt.Errorf("%s %s read response: %w", method, url, err)
	}
	// 重新包装 resp 供调用方读 StatusCode/Header（Body 已关闭，另返回 bytes）
	// 为了保持接口，返回一个仅含 StatusCode/Header 的浅拷贝
	shallow := &fhttp.Response{
		StatusCode: resp.StatusCode,
		Header:     resp.Header,
	}
	return shallow, b, nil
}

func mustJSON(v any) []byte {
	b, _ := json.Marshal(v)
	return b
}
func truncateBody(b []byte) string {
	s := string(b)
	if len(s) > 500 {
		return s[:500] + "…[truncated]"
	}
	return s
}
