package importer

import (
	"encoding/json"
	"net/http"
)

// CPA 对等 cpa_service.py
type CPAAccount struct {
	Email string `json:"email"`
	Token string `json:"token"`
}

func FetchCPA(url string) ([]CPAAccount, error) {
	resp, err := http.Get(url)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out []CPAAccount
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	return out, nil
}
