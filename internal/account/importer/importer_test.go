package importer

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestImportCPA(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode([]Account{{Email:"a@a.com", Token:"tok"}, {Email:"b@b.com", Token:""}})
	}))
	defer srv.Close()
	accs, err := ImportFromCPA(srv.URL)
	if err != nil { t.Fatal(err) }
	if len(accs)!=1 { t.Fatalf("filter failed %v", accs) }
}
func TestImportSub2API(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer mytok" { w.WriteHeader(401); return }
		_ = json.NewEncoder(w).Encode([]Account{{Token:"x"}})
	}))
	defer srv.Close()
	accs, _ := ImportFromSub2API(srv.URL, "mytok")
	if len(accs)!=1 { t.Fatal() }
}
