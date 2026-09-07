package backend

import (
	"context"
	"time"

	fhttp "github.com/bogdanfinn/fhttp"
)

// VerifyToken 401 验活：GET /backend-api/me，2xx 视为有效。
// 供 scheduler 每日验活与存量清洗用（对等 Python _get_me 的健康语义）。
func (b *Backend) VerifyToken(ctx context.Context) error {
	path := "/backend-api/me"
	headers := b.RequestHeaders(path, map[string]string{"Accept": "application/json"})
	reqCtx, cancel := context.WithTimeout(ctx, 25*time.Second)
	defer cancel()
	resp, body, err := b.doJSONRequest(reqCtx, fhttp.MethodGet, b.BaseURL+path, headers, nil)
	if err != nil {
		return err
	}
	if err := ensureOK(resp.StatusCode, resp.Header.Get("Retry-After"), body, path, "account"); err != nil {
		return err
	}
	return nil
}
