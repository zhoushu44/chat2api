package account

import "testing"

func TestAccountService(t *testing.T) {
	s := New(t.TempDir())
	a := &Account{ID: "a1", Email: "test@example.com", Token: "tok", SourceType: "codex", Type: "Plus", FP: map[string]string{"user-agent":"ua"}}
	if err := s.Add(a); err != nil { t.Fatal(err) }
	if _, ok := s.Get("a1"); !ok { t.Fatal() }
	if len(s.List()) != 1 { t.Fatal() }
	s2 := New(s.dir)
	if len(s2.List()) != 1 { t.Fatal("persist failed") }
	if NormalizeSourceType("codex") != "codex" { t.Fatal() }
	if NormalizeAccountType("Plus") != "Plus" { t.Fatal() }
}
