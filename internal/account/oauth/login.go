package oauth

import (
	"fmt"
	"net/url"
)

// 对等 services/oauth_login_service.py
func BuildLoginURL(clientID, redirectURI, state string) string {
	v := url.Values{}
	v.Set("client_id", clientID)
	v.Set("redirect_uri", redirectURI)
	v.Set("response_type", "code")
	v.Set("scope", "openid email profile")
	v.Set("state", state)
	v.Set("code_challenge_method", "S256")
	return "https://auth.openai.com/authorize?" + v.Encode()
}

func ExchangeCode(code, verifier string) (string, error) {
	if code == "" || verifier == "" {
		return "", fmt.Errorf("code/verifier required")
	}
	// 桩：返回模拟 token
	return "access-" + code[:4], nil
}
