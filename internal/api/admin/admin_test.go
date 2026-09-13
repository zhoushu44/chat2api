package admin

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"chatgpt2api/internal/account"
	"chatgpt2api/internal/config"

	"github.com/gin-gonic/gin"
)

func TestAdminAccounts(t *testing.T) {
	gin.SetMode(gin.TestMode)
	w := httptest.NewRecorder()
	_, r := gin.CreateTestContext(w)
	dir := t.TempDir()
	svc := account.New(dir)
	h := &AccountsHandler{Accounts: svc}
	g := r.Group("/api")
	h.Register(g)
	// create
	body,_:=json.Marshal(map[string]string{"email":"a@a.com","token":"tok","type":"Plus"})
	req,_:=http.NewRequest("POST","/api/accounts", bytes.NewReader(body))
	req.Header.Set("Content-Type","application/json")
	r.ServeHTTP(w, req)
	if w.Code!=200 { t.Fatalf("code %d", w.Code) }

	// batch import（RegiForge auto-import 与前端批量导入格式）
	batch,_:=json.Marshal(map[string]any{"accounts":[]map[string]any{
		{"access_token":"tok-batch-1","email":"b@a.com","type":"free","source_type":"web"},
		{"access_token":"tok-batch-2","email":"c@a.com"},
	}, "tokens":[]string{}})
	w=httptest.NewRecorder()
	req,_=http.NewRequest("POST","/api/accounts", bytes.NewReader(batch))
	req.Header.Set("Content-Type","application/json")
	r.ServeHTTP(w, req)
	if w.Code!=200 { t.Fatalf("batch code %d", w.Code) }
	var resp struct{ Added int `json:"added"`; Skipped int `json:"skipped"`; Errors []any `json:"errors"` }
	_=json.NewDecoder(w.Body).Decode(&resp)
	if resp.Added!=2 || resp.Skipped!=0 || len(resp.Errors)!=0 {
		t.Fatalf("batch resp %+v", resp)
	}
	if len(svc.List())!=3 { t.Fatalf("accounts = %d, want 3", len(svc.List())) }

	// list
	w=httptest.NewRecorder()
	req,_=http.NewRequest("GET","/api/accounts", nil)
	r.ServeHTTP(w, req)
	if w.Code!=200 { t.Fatal() }
}

func TestSystem(t *testing.T) {
	gin.SetMode(gin.TestMode)
	w:=httptest.NewRecorder()
	_, r:=gin.CreateTestContext(w)
	cfg,_:=config.Load("")
	h:=&SystemHandler{Cfg:cfg}
	g:=r.Group("/api")
	h.Register(g)
	w=httptest.NewRecorder()
	req,_:=http.NewRequest("GET","/api/config", nil)
	r.ServeHTTP(w,req)
	if w.Code!=200 { t.Fatal() }
}
