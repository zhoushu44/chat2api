package proxy

import "testing"

func TestPick(t *testing.T) {
	if Pick("a","b","c","d")!="a" { t.Fatal() }
	if Pick("","b","c","d")!="b" { t.Fatal() }
	if Pick("","","c","d")!="c" { t.Fatal() }
	if Pick("","","","d")!="d" { t.Fatal() }
	if !IsValid("http://127.0.0.1:7890") { t.Fatal() }
	if IsValid("://bad") { t.Fatal() }
}
