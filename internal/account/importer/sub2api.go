package importer

import (
	"encoding/json"
	"net/http"
)

// Sub2API 对等 sub2api_service.py
type Sub2APIAccount struct {
	Email string `json:"email"`
	Token string `json:"token"`
}

func FetchSub2API(url, token string) ([]Sub2APIAccount, error) {
	req, _ := http.NewRequest("GET", url, nil)
	req.Header.Set("Authorization", "Bearer "+token)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var out []Sub2APIAccount
	_ = json.NewDecoder(resp.Body).Decode(&out)
	return out, nil
}
