package fingerprint

import (
	"sync/atomic"
)

// Profile 对齐 abai ProtocolEnvironmentProfile
type Profile struct {
	Name                string `json:"name"`
	Impersonate         string `json:"impersonate"`
	UserAgent           string `json:"user_agent"`
	AcceptLanguage      string `json:"accept_language"`
	Language            string `json:"language"`
	Languages           []string `json:"languages"`
	Timezone            string `json:"timezone"`
	ScreenWidth         int    `json:"screen_width"`
	ScreenHeight        int    `json:"screen_height"`
	HardwareConcurrency int    `json:"hardware_concurrency"`
	SdkURL              string `json:"sdk_url"`
}

const chromeVer = "146"
const chromeImpersonate = "chrome146"

func desktopUSChromeV1() Profile {
	return Profile{
		Name: "desktop-us-en-chrome-v1", Impersonate: chromeImpersonate,
		UserAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
		AcceptLanguage: "en-US,en;q=0.9", Language: "en-US", Languages: []string{"en-US", "en"},
		Timezone: "America/New_York", ScreenWidth: 1920, ScreenHeight: 1080, HardwareConcurrency: 8,
		SdkURL: "https://sentinel.openai.com/sentinel/20260219f9f6/sdk.js",
	}
}
func desktopUSChromeV2() Profile {
	return Profile{
		Name: "desktop-us-en-chrome-v2", Impersonate: chromeImpersonate,
		UserAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
		AcceptLanguage: "en-US,en;q=0.9", Language: "en-US", Languages: []string{"en-US", "en"},
		Timezone: "America/Chicago", ScreenWidth: 2560, ScreenHeight: 1440, HardwareConcurrency: 16,
		SdkURL: "https://sentinel.openai.com/sentinel/20260219f9f6/sdk.js",
	}
}
func desktopUSChromeV3() Profile {
	return Profile{
		Name: "desktop-us-en-chrome-v3", Impersonate: chromeImpersonate,
		UserAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
		AcceptLanguage: "en-US,en;q=0.9", Language: "en-US", Languages: []string{"en-US", "en"},
		Timezone: "America/Los_Angeles", ScreenWidth: 1680, ScreenHeight: 1050, HardwareConcurrency: 10,
		SdkURL: "https://sentinel.openai.com/sentinel/20260219f9f6/sdk.js",
	}
}
func desktopUSChromeV4() Profile {
	return Profile{
		Name: "desktop-us-en-chrome-v4", Impersonate: chromeImpersonate,
		UserAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
		AcceptLanguage: "en-US,en;q=0.9", Language: "en-US", Languages: []string{"en-US", "en"},
		Timezone: "America/Denver", ScreenWidth: 1366, ScreenHeight: 768, HardwareConcurrency: 4,
		SdkURL: "https://sentinel.openai.com/sentinel/20260219f9f6/sdk.js",
	}
}
func desktopUSChromeV5() Profile {
	return Profile{
		Name: "desktop-us-en-chrome-v5", Impersonate: chromeImpersonate,
		UserAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
		AcceptLanguage: "en-US,en;q=0.9", Language: "en-US", Languages: []string{"en-US", "en"},
		Timezone: "America/New_York", ScreenWidth: 1440, ScreenHeight: 900, HardwareConcurrency: 6,
		SdkURL: "https://sentinel.openai.com/sentinel/20260219f9f6/sdk.js",
	}
}
func desktopUSChromeV6() Profile {
	return Profile{
		Name: "desktop-us-en-chrome-v6", Impersonate: chromeImpersonate,
		UserAgent: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
		AcceptLanguage: "en-US,en;q=0.9", Language: "en-US", Languages: []string{"en-US", "en"},
		Timezone: "America/Chicago", ScreenWidth: 1920, ScreenHeight: 1080, HardwareConcurrency: 12,
		SdkURL: "https://sentinel.openai.com/sentinel/20260219f9f6/sdk.js",
	}
}

// Pool 指纹池，round-robin，对齐 abai FingerprintPool
type Pool struct {
	profiles []Profile
	idx      atomic.Uint64
}

func NewPool() *Pool {
	return &Pool{profiles: []Profile{
		desktopUSChromeV1(), desktopUSChromeV2(), desktopUSChromeV3(),
		desktopUSChromeV4(), desktopUSChromeV5(), desktopUSChromeV6(),
	}}
}

func (p *Pool) Next() Profile {
	i := p.idx.Add(1) - 1
	return p.profiles[int(i%uint64(len(p.profiles)))]
}

func (p *Pool) All() []Profile { return append([]Profile(nil), p.profiles...) }

// 全局池，对齐 abai _fingerprint_pool = FingerprintPool.from_us_en_desktop()
var DefaultPool = NewPool()
