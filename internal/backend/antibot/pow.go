package antibot

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"math/rand"
	"regexp"
	"strings"
	"time"

	"github.com/google/uuid"
)

const DefaultPowScript = "https://chatgpt.com/backend-api/sentinel/sdk.js"

var (
	screenResolutions = [][]int{{1920, 1080}, {1440, 900}, {2560, 1440}, {3840, 2160}}
	cores             = []int{8, 16, 24, 32}
	documentKeys      = []string{"__reactContainer$fzelfjyxej8", "_reactListening5dehydibo78", "location"}
	navigatorKeys     = []string{
		"registerProtocolHandler−function registerProtocolHandler() { [native code] }",
		"storage−[object StorageManager]",
		"locks−[object LockManager]",
		"appCodeName−Mozilla",
		"permissions−[object Permissions]",
		"share−function share() { [native code] }",
		"webdriver−false",
		"managed−[object NavigatorManagedData]",
		"canShare−function canShare() { [native code] }",
		"vendor−Google Inc.",
		"mediaDevices−[object MediaDevices]",
		"vibrate−function vibrate() { [native code] }",
		"storageBuckets−[object StorageBucketManager]",
		"mediaCapabilities−[object MediaCapabilities]",
		"cookieEnabled−true",
		"virtualKeyboard−[object VirtualKeyboard]",
		"product−Gecko",
		"presentation−[object Presentation]",
		"onLine−true",
		"mimeTypes−[object MimeTypeArray]",
		"credentials−[object CredentialsContainer]",
		"serviceWorker−[object ServiceWorkerContainer]",
		"keyboard−[object Keyboard]",
		"gpu−[object GPU]",
		"doNotTrack",
		"serial−[object Serial]",
		"pdfViewerEnabled−true",
		"language−zh-CN",
		"geolocation−[object Geolocation]",
		"userAgentData−[object NavigatorUAData]",
		"getUserMedia−function getUserMedia() { [native code] }",
		"sendBeacon−function sendBeacon() { [native code] }",
		"hardwareConcurrency−32",
		"windowControlsOverlay−[object WindowControlsOverlay]",
	}
	windowKeys = []string{
		"0", "window", "self", "document", "name", "location", "customElements", "history",
		"navigation", "innerWidth", "innerHeight", "scrollX", "scrollY", "visualViewport",
		"screenX", "screenY", "outerWidth", "outerHeight", "devicePixelRatio", "screen",
		"chrome", "navigator", "onresize", "performance", "crypto", "indexedDB", "sessionStorage",
		"localStorage", "scheduler", "alert", "atob", "btoa", "fetch", "matchMedia",
		"postMessage", "queueMicrotask", "requestAnimationFrame", "setInterval", "setTimeout",
		"caches", "__NEXT_DATA__", "__BUILD_MANIFEST", "__NEXT_PRELOADREADY",
	}
	buildRe  = regexp.MustCompile(`c/[^/]*/_`)
	dataBuildAttrRe = regexp.MustCompile(`<html[^>]*data-build="([^"]*)"`)
	scriptSrcRe     = regexp.MustCompile(`<script[^>]+src="([^"]+)"`)
)

// ParsePowResources 从首页 HTML 提取 script 源与 data-build（对等 utils/pow.parse_pow_resources）。
func ParsePowResources(html string) ([]string, string) {
	var sources []string
	matches := scriptSrcRe.FindAllStringSubmatch(html, -1)
	for _, m := range matches {
		if len(m) >= 2 {
			src := m[1]
			sources = append(sources, src)
		}
	}
	if len(sources) == 0 {
		sources = []string{DefaultPowScript}
	}
	dataBuild := ""
	for _, src := range sources {
		if mm := buildRe.FindString(src); mm != "" {
			dataBuild = mm
			break
		}
	}
	if dataBuild == "" {
		if mm := dataBuildAttrRe.FindStringSubmatch(html); len(mm) == 2 {
			dataBuild = mm[1]
		}
	}
	return sources, dataBuild
}

func legacyParseTime() string {
	// Python: datetime.now(timezone -5) 格式 "%a %b %d %Y %H:%M:%S" + " GMT-0500 (Eastern Standard Time)"
	loc := time.FixedZone("EST", -5*3600)
	now := time.Now().In(loc)
	return now.Format("Mon Jan 02 2006 15:04:05") + " GMT-0500 (Eastern Standard Time)"
}

func buildPowConfig(userAgent string, scriptSources []string, dataBuild string) []any {
	// 复用全局 rand（已加锁，避免每调用 NewSource 分配）
	res := screenResolutions[rand.Intn(len(screenResolutions))]
	sumRes := res[0] + res[1]
	navKey := navigatorKeys[rand.Intn(len(navigatorKeys))]
	docKey := documentKeys[rand.Intn(len(documentKeys))]
	winKey := windowKeys[rand.Intn(len(windowKeys))]
	scriptSource := DefaultPowScript
	if len(scriptSources) > 0 {
		scriptSource = scriptSources[rand.Intn(len(scriptSources))]
	}
	perfNow := float64(rand.Intn(49000)+1000) + rand.Float64()
	now := time.Now()
	// perf_counter *1000 近似用 perfNow
	return []any{
		sumRes,
		legacyParseTime(),
		4294705152,
		1,
		userAgent,
		scriptSource,
		dataBuild,
		"en-US",
		"en-US,es-US,en,es",
		rand.Float64(),
		navKey,
		docKey,
		winKey,
		perfNow,
		uuid.NewString(),
		"",
		cores[rand.Intn(len(cores))],
		float64(now.UnixMilli()) - perfNow,
	}
}

// powGenerate 在 config 上寻找满足 difficulty 的编码（对等 _pow_generate）。
func powGenerate(seed, difficulty string, config []any, limit int) (string, bool) {
	if difficulty == "" {
		difficulty = "0"
	}
	// 预序列化三段（复刻 Python 的切片拼接，避免重复 json 编码）
	static1JSON, _ := json.Marshal(config[:3])
	static1 := append([]byte(strings.TrimSuffix(string(static1JSON), "]")+","), []byte{}...)
	static2JSON, _ := json.Marshal(config[4:9])
	s2 := string(static2JSON)
	if len(s2) >= 2 {
		s2 = s2[1 : len(s2)-1]
	}
	static2 := []byte("," + s2 + ",")
	static3JSON, _ := json.Marshal(config[10:])
	s3 := string(static3JSON)
	if len(s3) >= 2 {
		s3 = s3[1:]
	} else {
		s3 = "[]"
	}
	static3 := []byte("," + s3)

	for i := 0; i < limit; i++ {
		part := fmt.Sprintf("%s%d%s%d%s", string(static1), i, string(static2), i>>1, string(static3))
		encoded := base64.StdEncoding.EncodeToString([]byte(part))
		hash := fnv1aHash(seed + encoded)
		if hash[:len(difficulty)] <= difficulty {
			return encoded, true
		}
	}
	fallback := "wQ8Lk5FbGpA2NcR9dShT6gYjU7VxZ4D" + base64.StdEncoding.EncodeToString([]byte(`"`+seed+`"`))
	return fallback, false
}

// fnv1aHash 实现 FNV-1a 32-bit + 额外混合（对等官方 Sentinel SDK 的 hash 函数）。
func fnv1aHash(text string) string {
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

// BuildLegacyRequirementsToken 生成 requirements 阶段的 p token（对等 build_legacy_requirements_token）。
func BuildLegacyRequirementsToken(userAgent string, scriptSources []string, dataBuild string) string {
	config := buildPowConfig(userAgent, scriptSources, dataBuild)
	b, _ := json.Marshal(config)
	return "gAAAAAC" + base64.StdEncoding.EncodeToString(b)
}

// BuildProofToken 生成 finalize 阶段的 proof token。
// fix9: 移除全局 30s TTL 缓存——原实现在并发下多账号共享同一 proof token，
// 是上游风控的强关联信号（sentinel token 一次性 + proof 字串一字不差跨账号复用）。
// FNV-1a 现算成本实测 <5ms（50万次上限内），换来每请求唯一 token。
func BuildProofToken(seed, difficulty, userAgent string, scriptSources []string, dataBuild string) (string, error) {
	if seed == "" || difficulty == "" {
		return BuildLegacyRequirementsToken(userAgent, scriptSources, dataBuild), nil
	}
	config := buildPowConfig(userAgent, scriptSources, dataBuild)
	answer, solved := powGenerate(seed, difficulty, config, 500000)
	if !solved {
		return "", fmt.Errorf("failed to solve proof token: difficulty=%s", difficulty)
	}
	return "gAAAAAB" + answer + "~S", nil
}
