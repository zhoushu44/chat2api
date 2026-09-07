package antibot

import (
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"math"
	"time"

	"github.com/google/uuid"
)

const (
	DefaultSentinelUserAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
	DefaultSentinelSecChUa   = `"Chromium";v="145", "Google Chrome";v="145", "Not/A)Brand";v="99"`
)

// SentinelTokenGenerator 对应 Python SentinelTokenGenerator（简化版）。
type SentinelTokenGenerator struct {
	DeviceID  string
	UserAgent string
	SID       string
}

func NewSentinelTokenGenerator(deviceID, ua string) *SentinelTokenGenerator {
	if ua == "" {
		ua = DefaultSentinelUserAgent
	}
	return &SentinelTokenGenerator{
		DeviceID:  deviceID,
		UserAgent: ua,
		SID:       uuid.NewString(),
	}
}

func (s *SentinelTokenGenerator) fnv1a32(text string) string {
	h := uint32(2166136261)
	for _, ch := range text {
		h ^= uint32(ch)
		h *= 16777619
	}
	h ^= h >> 16
	h *= 2246822507
	h ^= h >> 13
	h *= 3266489909
	h ^= h >> 16
	return fmt.Sprintf("%08x", h)
}

func (s *SentinelTokenGenerator) getConfig() []any {
	perfNow := float64(1000 + randInt(49000)) + randFloat()
	return []any{
		"1920x1080",
		time.Now().UTC().Format("Mon Jan 02 2006 15:04:05 GMT+0000 (Coordinated Universal Time)"),
		4294705152,
		randFloat(),
		s.UserAgent,
		"https://sentinel.openai.com/sentinel/20260219f9f6/sdk.js",
		nil,
		nil,
		"en-US",
		randFloat(),
		pick([]string{"vendorSub-undefined", "plugins-undefined", "mimeTypes-undefined", "hardwareConcurrency-undefined"}),
		pick([]string{"location", "implementation", "URL", "documentURI", "compatMode"}),
		pick([]string{"Object", "Function", "Array", "Number", "parseFloat", "undefined"}),
		perfNow,
		s.SID,
		"",
		pick([]int{4, 8, 12, 16}),
		float64(time.Now().UnixMilli()) - perfNow,
	}
}

func randInt(n int) int {
	b := make([]byte, 4)
	_, _ = rand.Read(b)
	v := int(b[0])<<24 | int(b[1])<<16 | int(b[2])<<8 | int(b[3])
	if v < 0 {
		v = -v
	}
	return v % n
}
func randFloat() float64 {
	b := make([]byte, 8)
	_, _ = rand.Read(b)
	var v uint64
	for i := 0; i < 8; i++ {
		v = v<<8 | uint64(b[i])
	}
	return float64(v%1_000_000) / 1_000_000
}
func pick[T any](arr []T) T { return arr[randInt(len(arr))] }

func b64(data any) string {
	j, _ := json.Marshal(data)
	return base64.StdEncoding.EncodeToString(j)
}

// GenerateRequirementsToken 生成 sentinel requirements token（gAAAAAC 前缀）。
func (s *SentinelTokenGenerator) GenerateRequirementsToken() string {
	cfg := s.getConfig()
	cfg[3] = 1
	cfg[9] = math.Round(float64(5 + randInt(45)))
	return "gAAAAAC" + b64(cfg)
}

// GenerateToken 生成 proof 场景 token（gAAAAAB 前缀），满足 FNV1a 难度。
func (s *SentinelTokenGenerator) GenerateToken(seed, difficulty string) string {
	if difficulty == "" {
		difficulty = "0"
	}
	start := time.Now()
	cfg := s.getConfig()
	for i := 0; i < 500000; i++ {
		cfg[3] = i
		cfg[9] = math.Round(float64(time.Since(start).Milliseconds()))
		payload := b64(cfg)
		if s.fnv1a32(seed+payload)[:len(difficulty)] <= difficulty {
			return "gAAAAAB" + payload + "~S"
		}
	}
	return "gAAAAAB" + "wQ8Lk5FbGpA2NcR9dShT6gYjU7VxZ4D" + b64(nil)
}
