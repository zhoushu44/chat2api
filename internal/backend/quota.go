package backend

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	fhttp "github.com/bogdanfinn/fhttp"
)

// AccountQuota 远程账号状态探测结果（对等 Python refresh_accounts 的字段口径）。
// quota：图片剩余额度；ok=false 表示 token 失效/网络失败，此时 quota 不可信。
// planType：上游 plan（free/plus/team 等），空串表示未识别。
type AccountQuota struct {
	OK       bool
	Quota    int
	PlanType string
}

// quotaPath 探测图片额度的官方路径。
// ChatGPT web 端 rate_limits 汇总接口，image_gen 下含 used/limit 等字段。
const quotaPath = "/backend-api/rate_limits"

// FetchAccountQuota 拉取账号远程图片额度（对等 Python refresh_accounts 单号探测）。
// 探测链路：GET /backend-api/rate_limits?feature=image_gen
// 返回 401 → OK=false（token 失效，调用方按验活失败语义处理）。
func (b *Backend) FetchAccountQuota(ctx context.Context) (AccountQuota, error) {
	full := b.BaseURL + quotaPath + "?feature=image_gen"
	headers := b.RequestHeaders(quotaPath, map[string]string{"Accept": "application/json"})
	reqCtx, cancel := context.WithTimeout(ctx, 25*time.Second)
	defer cancel()
	resp, body, err := b.doJSONRequest(reqCtx, fhttp.MethodGet, full, headers, nil)
	if err != nil {
		return AccountQuota{}, err
	}
	if err := ensureOK(resp.StatusCode, resp.Header.Get("Retry-After"), body, quotaPath, "account"); err != nil {
		return AccountQuota{}, err
	}
	return parseAccountQuota(body)
}

// parseAccountQuota 解析 rate_limits 响应（容错：上游字段形状随版本漂移）。
// 已知形状（2026-09 实测）：
//
//	{"rate_limits":[{"feature":"image_gen","used_metric":3,"max_limit":100,
//	 "quota_type":"primary","resets_in":1800.0}, ...]}
//
// 兼容旧形状：{"image_gen":{"used":..,"limit":..}} 或顶层 {"rate_limits":{...}}。
func parseAccountQuota(body []byte) (AccountQuota, error) {
	var raw map[string]any
	if err := json.Unmarshal(body, &raw); err != nil {
		return AccountQuota{}, fmt.Errorf("parse quota response: %w", err)
	}
	out := AccountQuota{OK: true}
	if plan := quotaPlanFrom(raw); plan != "" {
		out.PlanType = plan
	}
	if q, ok := quotaFromRateLimits(raw); ok {
		out.Quota = q
		return out, nil
	}
	if q, ok := quotaFromImageGenMap(raw); ok {
		out.Quota = q
		return out, nil
	}
	// 形状不识别：额度未知但账号验活通过（quota_unknown 语义），不报错
	out.Quota = 0
	return out, nil
}

// quotaFromRateLimits 新形状：rate_limits 为数组，找 feature=image_gen 项。
func quotaFromRateLimits(raw map[string]any) (int, bool) {
	arr, ok := raw["rate_limits"].([]any)
	if !ok {
		return 0, false
	}
	for _, item := range arr {
		m, ok := item.(map[string]any)
		if !ok {
			continue
		}
		feat, _ := m["feature"].(string)
		if !strings.Contains(strings.ToLower(feat), "image") {
			continue
		}
		limit := quotaFloat(m, "max_limit", "limit")
		used := quotaFloat(m, "used_metric", "used")
		if limit <= 0 && used <= 0 {
			continue
		}
		remaining := limit - used
		if remaining < 0 {
			remaining = 0
		}
		// limit=0 且 used=0：上游明确「无配额」
		if limit == 0 {
			return 0, true
		}
		return int(remaining), true
	}
	return 0, false
}

// quotaFromImageGenMap 旧形状：image_gen 为对象 {used, limit}。
func quotaFromImageGenMap(raw map[string]any) (int, bool) {
	m, ok := raw["image_gen"].(map[string]any)
	if !ok {
		return 0, false
	}
	limit := quotaFloat(m, "limit", "max_limit")
	used := quotaFloat(m, "used", "used_metric")
	if limit == 0 {
		return 0, true
	}
	if limit < 0 {
		return -1, true // 无限额度哨兵
	}
	remaining := limit - used
	if remaining < 0 {
		remaining = 0
	}
	return int(remaining), true
}

// quotaPlanFrom 从响应里提取 plan 类型（chatgpt 官网 /me 的 plan 字段口径）。
func quotaPlanFrom(raw map[string]any) string {
	for _, key := range []string{"plan_type", "plan", "chatgpt_plan_type"} {
		if v, ok := raw[key].(string); ok && v != "" {
			return normalizeQuotaPlan(v)
		}
	}
	return ""
}

func normalizeQuotaPlan(v string) string {
	switch strings.ToLower(strings.TrimSpace(v)) {
	case "free":
		return "Free"
	case "plus":
		return "Plus"
	case "team":
		return "Team"
	case "pro":
		return "Pro"
	default:
		return strings.TrimSpace(v)
	}
}

// quotaFloat 从 map 里按候选键取数值（json 数字默认 float64）。
func quotaFloat(m map[string]any, keys ...string) float64 {
	for _, k := range keys {
		if v, ok := m[k].(float64); ok {
			return v
		}
		if v, ok := m[k].(int); ok {
			return float64(v)
		}
	}
	return -1
}
