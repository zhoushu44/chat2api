package importer

import (
	"encoding/json"
	"net/http"
)

type Account struct {
	Email string `json:"email"`
	Token string `json:"token"`
	Type  string `json:"type"`
}

func ImportFromCPA(url string) ([]Account, error) {
	resp, err := http.Get(url)
	if err != nil { return nil, err }
	defer resp.Body.Close()
	var out []Account
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil { return nil, err }
	return filter(out), nil
}
func ImportFromSub2API(url, token string) ([]Account, error) {
	req, _ := http.NewRequest("GET", url, nil)
	req.Header.Set("Authorization", "Bearer "+token)
	resp, err := http.DefaultClient.Do(req)
	if err != nil { return nil, err }
	defer resp.Body.Close()
	var out []Account
	_ = json.NewDecoder(resp.Body).Decode(&out)
	return filter(out), nil
}
func filter(in []Account) []Account {
	var out []Account
	for _, a := range in {
		if a.Token != "" { out = append(out, a) }
	}
	return out
}
