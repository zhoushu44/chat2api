package antibot

import (
	"encoding/base64"
	"testing"
)

func TestGeneratePKCE(t *testing.T) {
	v, c, err := GeneratePKCE()
	if err != nil {
		t.Fatalf("GeneratePKCE: %v", err)
	}
	if v == "" || c == "" {
		t.Fatalf("empty: v=%q c=%q", v, c)
	}
	// verifier 应为 base64url 无 padding
	if _, err := base64.RawURLEncoding.DecodeString(v); err != nil {
		t.Fatalf("verifier not base64url: %v", err)
	}
	if _, err := base64.RawURLEncoding.DecodeString(c); err != nil {
		t.Fatalf("challenge not base64url: %v", err)
	}
	if v == c {
		t.Fatalf("verifier == challenge")
	}
}

