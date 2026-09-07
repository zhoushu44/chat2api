package antibot

import (
	"crypto/sha3"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"math/rand"
	"regexp"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"
	"golang.org/x/sync/singleflight"
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
		0, 0, 0, 0, 0, 0,
		0,
	}
}

// powGenerate 在 config 上寻找满足 difficulty 的编码（对等 _pow_generate）。
func powGenerate(seed, difficulty string, config []any, limit int) (string, bool) {
	if difficulty == "" {
		difficulty = "0"
	}
	// difficulty 为 hex 字符串，转目标字节
	target, err := hexToBytes(difficulty)
	if err != nil {
		target = []byte{0}
	}
	diffLen := len(difficulty) / 2
	seedBytes := []byte(seed)
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
		h := sha3.New512()
		h.Write(seedBytes)
		h.Write([]byte(encoded))
		digest := h.Sum(nil)
		if len(digest) >= diffLen {
			le := true
			for k := 0; k < diffLen; k++ {
				if digest[k] > target[k] {
					le = false
					break
				} else if digest[k] < target[k] {
					break
				}
			}
			if le {
				return encoded, true
			}
		}
	}
	fallback := "wQ8Lk5FbGpA2NcR9dShT6gYjU7VxZ4D" + base64.StdEncoding.EncodeToString([]byte(`"`+seed+`"`))
	return fallback, false
}

func hexToBytes(s string) ([]byte, error) {
	if len(s)%2 == 1 {
		s = "0" + s
	}
	out := make([]byte, len(s)/2)
	for i := 0; i < len(out); i++ {
		var v byte
		_, err := fmt.Sscanf(s[i*2:i*2+2], "%02x", &v)
		if err != nil {
			// 手动解析
			hi := hexVal(s[i*2])
			lo := hexVal(s[i*2+1])
			v = hi<<4 | lo
		}
		out[i] = v
	}
	return out, nil
}
func hexVal(c byte) byte {
	switch {
	case c >= '0' && c <= '9':
		return c - '0'
	case c >= 'a' && c <= 'f':
		return c - 'a' + 10
	case c >= 'A' && c <= 'F':
		return c - 'A' + 10
	}
	return 0
}

var (
	proofCache   sync.Map // key -> cachedToken
	proofSF      singleflight.Group
)

type cachedToken struct {
	Token  string
	Expire time.Time
}

// BuildLegacyRequirementsToken 生成 requirements 阶段的 p token（对等 build_legacy_requirements_token）。
func BuildLegacyRequirementsToken(userAgent string, scriptSources []string, dataBuild string) string {
	config := buildPowConfig(userAgent, scriptSources, dataBuild)
	b, _ := json.Marshal(config)
	return "gAAAAAC" + base64.StdEncoding.EncodeToString(b)
}

// BuildProofToken 生成 finalize 阶段的 proof token（单flight + 30s TTL 缓存，避免 50万次 sha3 重算）。
func BuildProofToken(seed, difficulty, userAgent string, scriptSources []string, dataBuild string) (string, error) {
	if seed == "" || difficulty == "" {
		return BuildLegacyRequirementsToken(userAgent, scriptSources, dataBuild), nil
	}
	key := seed + "|" + difficulty + "|" + userAgent
	if v, ok := proofCache.Load(key); ok {
		if ct, ok := v.(cachedToken); ok && time.Now().Before(ct.Expire) {
			return ct.Token, nil
		}
	}
	val, err, _ := proofSF.Do(key, func() (any, error) {
		// 双检
		if v, ok := proofCache.Load(key); ok {
			if ct, ok := v.(cachedToken); ok && time.Now().Before(ct.Expire) {
				return ct.Token, nil
			}
		}
		config := buildPowConfig(userAgent, scriptSources, dataBuild)
		answer, solved := powGenerate(seed, difficulty, config, 500000)
		if !solved {
			return "", fmt.Errorf("failed to solve proof token: difficulty=%s", difficulty)
		}
		tok := "gAAAAAB" + answer
		proofCache.Store(key, cachedToken{Token: tok, Expire: time.Now().Add(30 * time.Second)})
		return tok, nil
	})
	if err != nil {
		return "", err
	}
	return val.(string), nil
}
