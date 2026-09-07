// Command init-proxy-config:幂等地把 WARP/FlareSolverr proxy_runtime 默认值合并进 config.json。
// 对等 scripts/init_proxy_config.py（env 驱动 + 仓库默认/脚手架识别 + URL 脱敏输出）。
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
)

var defaultUA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"

func defaultRuntime() map[string]any {
	return map[string]any{
		"enabled": false, "egress_mode": "direct", "proxy_url": "",
		"resource_proxy_url": "", "skip_ssl_verify": false,
		"reset_session_status_codes": []any{403},
		"clearance": map[string]any{
			"enabled": false, "mode": "none", "cf_cookies": "", "cf_clearance": "",
			"user_agent": defaultUA, "browser": "chrome", "flaresolverr_url": "",
			"timeout_sec": 60, "refresh_interval": 3600, "warm_up_on_start": false,
		},
	}
}

func envBool(name string, def bool) bool {
	v, ok := os.LookupEnv(name)
	if !ok {
		return def
	}
	switch strings.ToLower(strings.TrimSpace(v)) {
	case "1", "true", "yes", "on":
		return true
	case "0", "false", "no", "off":
		return false
	default:
		return def
	}
}

func envInt(name string, def, min int) int {
	v := strings.TrimSpace(os.Getenv(name))
	if v == "" {
		return def
	}
	n, err := strconv.Atoi(v)
	if err != nil || n < min {
		return def
	}
	return n
}

func warpDefaults() map[string]any {
	clearanceEnabled := envBool("CHATGPT2API_PROXY_RUNTIME_CLEARANCE_ENABLED", true)
	clearanceMode := strings.ToLower(strings.TrimSpace(os.Getenv("CHATGPT2API_PROXY_RUNTIME_CLEARANCE_MODE")))
	if clearanceMode == "" {
		clearanceMode = "flaresolverr"
	}
	if clearanceMode != "none" && clearanceMode != "manual" && clearanceMode != "flaresolverr" {
		if clearanceEnabled {
			clearanceMode = "flaresolverr"
		} else {
			clearanceMode = "none"
		}
	}
	if !clearanceEnabled {
		clearanceMode = "none"
	}
	egress := strings.ToLower(strings.TrimSpace(os.Getenv("CHATGPT2API_PROXY_RUNTIME_EGRESS_MODE")))
	if egress == "" {
		egress = "single_proxy"
	}
	if egress != "direct" && egress != "single_proxy" {
		egress = "single_proxy"
	}
	var codes []any
	for _, part := range strings.Split(os.Getenv("CHATGPT2API_PROXY_RUNTIME_RESET_STATUS_CODES"), ",") {
		part = strings.TrimSpace(part)
		if n, err := strconv.Atoi(part); err == nil && n >= 100 && n <= 599 {
			codes = append(codes, n)
		}
	}
	if len(codes) == 0 {
		if os.Getenv("CHATGPT2API_PROXY_RUNTIME_RESET_STATUS_CODES") == "" {
			codes = []any{403}
		} else {
			codes = []any{403}
		}
	}
	rt := defaultRuntime()
	rt["enabled"] = envBool("CHATGPT2API_PROXY_RUNTIME_ENABLED", true)
	rt["egress_mode"] = egress
	rt["proxy_url"] = strings.TrimSpace(os.Getenv("CHATGPT2API_PROXY_RUNTIME_PROXY_URL"))
	if rt["proxy_url"] == "" {
		rt["proxy_url"] = "http://privoxy:8118"
	}
	rt["resource_proxy_url"] = strings.TrimSpace(os.Getenv("CHATGPT2API_PROXY_RUNTIME_RESOURCE_PROXY_URL"))
	rt["skip_ssl_verify"] = envBool("CHATGPT2API_PROXY_RUNTIME_SKIP_SSL_VERIFY", false)
	rt["reset_session_status_codes"] = codes
	cl := rt["clearance"].(map[string]any)
	cl["enabled"] = clearanceEnabled
	cl["mode"] = clearanceMode
	if ua := strings.TrimSpace(os.Getenv("CHATGPT2API_PROXY_RUNTIME_USER_AGENT")); ua != "" {
		cl["user_agent"] = ua
	}
	if br := strings.TrimSpace(os.Getenv("CHATGPT2API_PROXY_RUNTIME_BROWSER")); br != "" {
		cl["browser"] = br
	} else {
		cl["browser"] = "chrome"
	}
	cl["flaresolverr_url"] = strings.TrimSpace(os.Getenv("CHATGPT2API_FLARESOLVERR_URL"))
	if cl["flaresolverr_url"] == "" {
		cl["flaresolverr_url"] = "http://flaresolverr:8191"
	}
	cl["timeout_sec"] = envInt("CHATGPT2API_PROXY_RUNTIME_CLEARANCE_TIMEOUT_SEC", 60, 1)
	cl["refresh_interval"] = envInt("CHATGPT2API_PROXY_RUNTIME_CLEARANCE_REFRESH_INTERVAL", 3600, 60)
	cl["warm_up_on_start"] = envBool("CHATGPT2API_PROXY_RUNTIME_WARM_UP_ON_START", false)
	return rt
}

// deepFillMissing 递归补缺（返回是否变更）。
func deepFillMissing(target, defaults map[string]any) bool {
	changed := false
	for k, v := range defaults {
		ev, ok := target[k]
		if !ok {
			target[k] = v
			changed = true
			continue
		}
		em, eok := ev.(map[string]any)
		dm, dok := v.(map[string]any)
		if eok && dok && deepFillMissing(em, dm) {
			changed = true
		}
	}
	return changed
}

func mapsEqual(a, b map[string]any) bool {
	ab, _ := json.Marshal(a)
	bb, _ := json.Marshal(b)
	return string(ab) == string(bb)
}

func looksLikeRepoDefault(runtime any) bool {
	rm, ok := runtime.(map[string]any)
	if !ok {
		return true
	}
	candidate := map[string]any{}
	for k, v := range rm {
		candidate[k] = v
	}
	deepFillMissing(candidate, defaultRuntime())
	return mapsEqual(candidate, defaultRuntime())
}

func looksLikeInactiveWarpScaffold(runtime any) bool {
	rm, ok := runtime.(map[string]any)
	if !ok {
		return false
	}
	cl, _ := rm["clearance"].(map[string]any)
	if cl == nil {
		cl = map[string]any{}
	}
	toBool := func(v any) bool {
		b, _ := v.(bool)
		return b
	}
	return !toBool(rm["enabled"]) &&
		strings.ToLower(strings.TrimSpace(strVal(rm["egress_mode"]))) == "single_proxy" &&
		strings.TrimSpace(strVal(rm["proxy_url"])) == "http://privoxy:8118" &&
		toBool(cl["enabled"]) &&
		strings.ToLower(strings.TrimSpace(strVal(cl["mode"]))) == "flaresolverr" &&
		strings.TrimSpace(strVal(cl["flaresolverr_url"])) == "http://flaresolverr:8191" &&
		strings.TrimSpace(strVal(cl["cf_cookies"])) == "" &&
		strings.TrimSpace(strVal(cl["cf_clearance"])) == ""
}

func strVal(v any) string {
	s, _ := v.(string)
	return s
}

var maskRe = regexp.MustCompile(`(?i)(https?://)([^\s/@:]+):([^\s/@]+)@`)

func maskURL(v string) string {
	return maskRe.ReplaceAllString(v, "${1}[REDACTED]@")
}

func main() {
	configPath := flag.String("config", os.Getenv("CHATGPT2API_CONFIG_FILE"), "config.json 路径")
	flag.Parse()
	if *configPath == "" {
		*configPath = "config.json"
	}
	var data map[string]any
	raw, err := os.ReadFile(*configPath)
	if err != nil {
		if os.IsNotExist(err) {
			fmt.Printf("Config file not found, creating %s\n", *configPath)
			data = map[string]any{}
		} else {
			fmt.Fprintf(os.Stderr, "read %s: %v\n", *configPath, err)
			os.Exit(1)
		}
	} else {
		if err := json.Unmarshal(raw, &data); err != nil {
			fmt.Fprintf(os.Stderr, "Invalid JSON in %s: %v\n", *configPath, err)
			os.Exit(1)
		}
		if data == nil {
			fmt.Fprintf(os.Stderr, "Config root must be an object: %s\n", *configPath)
			os.Exit(1)
		}
	}

	desired := warpDefaults()
	existing := data["proxy_runtime"]
	changed := false
	if looksLikeRepoDefault(existing) || looksLikeInactiveWarpScaffold(existing) || envBool("CHATGPT2API_PROXY_RUNTIME_FORCE", false) {
		data["proxy_runtime"] = desired
		changed = true
		fmt.Println("Created proxy_runtime defaults")
	} else {
		runtime, _ := existing.(map[string]any)
		if runtime == nil {
			runtime = map[string]any{}
		}
		changed = deepFillMissing(runtime, defaultRuntime())
		data["proxy_runtime"] = runtime
		fmt.Println("Proxy runtime already configured")
	}

	if changed {
		_ = os.MkdirAll(filepath.Dir(*configPath), 0755)
		payload, _ := json.MarshalIndent(data, "", "  ")
		payload = append(payload, '\n')
		tmp := *configPath + ".tmp"
		if err := os.WriteFile(tmp, payload, 0644); err != nil {
			fmt.Fprintf(os.Stderr, "write: %v\n", err)
			os.Exit(1)
		}
		if err := os.Rename(tmp, *configPath); err != nil {
			// Docker 单文件 bind-mount 下 rename 可能 EBUSY → 回退直接写
			if err := os.WriteFile(*configPath, payload, 0644); err != nil {
				fmt.Fprintf(os.Stderr, "write: %v\n", err)
				os.Exit(1)
			}
			_ = os.Remove(tmp)
		}
	}

	runtime, _ := data["proxy_runtime"].(map[string]any)
	if runtime == nil {
		runtime = map[string]any{}
	}
	clearance, _ := runtime["clearance"].(map[string]any)
	if clearance == nil {
		clearance = map[string]any{}
	}
	enabled, _ := runtime["enabled"].(bool)
	fmt.Printf("Proxy runtime summary: enabled=%v, egress_mode=%v, proxy_url=%s, clearance_mode=%v, flaresolverr_url=%s\n",
		enabled, runtime["egress_mode"], maskURL(strVal(runtime["proxy_url"])),
		clearance["mode"], maskURL(strVal(clearance["flaresolverr_url"])))
}
