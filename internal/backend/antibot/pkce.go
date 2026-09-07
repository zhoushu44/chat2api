package antibot

import (
	"crypto/sha256"
	"encoding/base64"
	"crypto/rand"
)

// GeneratePKCE 生成 code_verifier 与 code_challenge（对等 utils/pkce.generate_pkce，S256）。
func GeneratePKCE() (verifier, challenge string, err error) {
	b := make([]byte, 64)
	if _, err = rand.Read(b); err != nil {
		return "", "", err
	}
	verifier = base64.RawURLEncoding.EncodeToString(b)
	h := sha256.Sum256([]byte(verifier))
	challenge = base64.RawURLEncoding.EncodeToString(h[:])
	return verifier, challenge, nil
}
