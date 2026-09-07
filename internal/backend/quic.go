package backend

import (
	"context"
	"crypto/tls"
	"net/http"
)

// QUIC 传输桩：真实可替换为 github.com/quic-go/quic-go + http3.RoundTripper
// 当前用标准 TLS 复用连接池模拟，接口一致，PGO 后可一键切换
type QUICTransport struct {
	base http.RoundTripper
}

func NewQUICTransport() *QUICTransport {
	return &QUICTransport{
		base: &http.Transport{
			TLSClientConfig: &tls.Config{InsecureSkipVerify: false},
			MaxIdleConns:    1000,
			MaxIdleConnsPerHost: 100,
			IdleConnTimeout: 90 * 1e9,
			ForceAttemptHTTP2: true,
		},
	}
}

func (q *QUICTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	// 预留 QUIC DATAGRAM 推送 file_ids，当前直通
	return q.base.RoundTrip(req)
}

func (q *QUICTransport) CloseIdleConnections() {
	if c, ok := q.base.(interface{ CloseIdleConnections() }); ok {
		c.CloseIdleConnections()
	}
}

var _ http.RoundTripper = (*QUICTransport)(nil)

// EnableQUIC 为 Backend 注入 QUIC 传输（架构级开关）
func (b *Backend) EnableQUIC(ctx context.Context) {
	// 桩：标记已启用，真实环境下替换 b.http 的 Transport
	_ = ctx
}
