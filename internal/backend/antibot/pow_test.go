package antibot

import (
	"encoding/base64"
	"encoding/json"
	"strings"
	"testing"
)

func TestBuildLegacyRequirementsToken(t *testing.T) {
	tok := BuildLegacyRequirementsToken("Mozilla/5.0", []string{DefaultPowScript}, "c/abc/_")
	if !strings.HasPrefix(tok, "gAAAAAC") {
		t.Fatalf("token prefix: %q", tok)
	}
	// 解码后应为合法 JSON 数组
	b, err := base64.StdEncoding.DecodeString(strings.TrimPrefix(tok, "gAAAAAC"))
	if err != nil {
		t.Fatalf("decode: %v", err)
	}
	var arr []any
	if err := json.Unmarshal(b, &arr); err != nil {
		t.Fatalf("json: %v body=%s", err, string(b))
	}
	if len(arr) < 20 {
		t.Fatalf("arr len %d", len(arr))
	}
}

func TestBuildProofToken(t *testing.T) {
	// 使用低难度，便于快速求解
	seed := "test-seed"
	difficulty := "0a" // 单字节目标，极易满足
	tok, err := BuildProofToken(seed, difficulty, "Mozilla/5.0", []string{DefaultPowScript}, "")
	if err != nil {
		t.Fatalf("BuildProofToken: %v", err)
	}
	if !strings.HasPrefix(tok, "gAAAAAB") {
		t.Fatalf("prefix: %q", tok)
	}
	// proof token 去掉前缀后应为 base64
	payload := strings.TrimPrefix(tok, "gAAAAAB")
	if _, err := base64.StdEncoding.DecodeString(payload); err != nil {
		// 可能是 fallback 带前缀，需容错
		if !strings.Contains(payload, "wQ8Lk5FbGpA2NcR9dShT6gYjU7VxZ4D") {
			t.Fatalf("payload not base64: %v", err)
		}
	}
}

func TestSentinelTokenGenerator(t *testing.T) {
	gen := NewSentinelTokenGenerator("device-123", "Mozilla/5.0")
	tok := gen.GenerateRequirementsToken()
	if !strings.HasPrefix(tok, "gAAAAAC") {
		t.Fatalf("sentinel prefix: %q", tok)
	}
	proof := gen.GenerateToken("seed-xyz", "0f")
	if !strings.HasPrefix(proof, "gAAAAAB") {
		t.Fatalf("proof prefix: %q", proof)
	}
}
