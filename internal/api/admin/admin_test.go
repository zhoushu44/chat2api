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
	svc := account.New(t.TempDir())
	h := &AccountsHandler{Accounts: svc}
	g := r.Group("/api")
	h.Register(g)
	// create
	body,_:=json.Marshal(map[string]string{"email":"a@a.com","token":"tok","type":"Plus"})
	req,_:=http.NewRequest("POST","/api/accounts", bytes.NewReader(body))
	req.Header.Set("Content-Type","application/json")
	r.ServeHTTP(w, req)
	if w.Code!=200 { t.Fatalf("code %d", w.Code) }
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
