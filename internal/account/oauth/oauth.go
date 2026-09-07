package oauth

import (
	"context"
	"encoding/json"
	"net/http"
	"sync"
	"time"

	"golang.org/x/sync/singleflight"
)

type Token struct {
	AccessToken  string `json:"access_token"`
	RefreshToken string `json:"refresh_token"`
	ExpiresAt    time.Time `json:"expires_at"`
}

type Refresher struct {
	mu    sync.RWMutex
	token *Token
	sf    singleflight.Group
	client *http.Client
}

func New(tok *Token) *Refresher {
	return &Refresher{token: tok, client: &http.Client{Timeout: 10*time.Second}}
}
func (r *Refresher) Get() *Token {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return r.token
}
func (r *Refresher) Refresh(ctx context.Context, refreshURL string) (*Token, error) {
	v, err, _ := r.sf.Do("refresh", func() (any, error) {
		req, _ := http.NewRequestWithContext(ctx, "POST", refreshURL, nil)
		resp, err := r.client.Do(req)
		if err != nil { return nil, err }
		defer resp.Body.Close()
		var tok Token
		if err := json.NewDecoder(resp.Body).Decode(&tok); err != nil { return nil, err }
		r.mu.Lock()
		r.token = &tok
		r.mu.Unlock()
		return &tok, nil
	})
	if err != nil { return nil, err }
	return v.(*Token), nil
}
func NeedsRefresh(tok *Token, lead time.Duration) bool {
	if tok == nil { return true }
	return time.Until(tok.ExpiresAt) < lead
}
