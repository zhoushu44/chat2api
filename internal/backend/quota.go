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

// conversationInitPath 探测图片额度的官方路径。
// POST /backend-api/conversation/init 响应 limits_progress[] 里 feature_name=="image_gen"
// 的 remaining 即图片剩余额度（reset_after 为恢复时间）。
// 注：旧的 GET /backend-api/rate_limits?feature=image_gen 已下线（404）。
const conversationInitPath = "/backend-api/conversation/init"

// conversationInitBody 探测额度用的固定请求体（对等 Python _get_conversation_init）。
var conversationInitBody = []byte(`{"gizmo_id":null,"requested_default_model":null,"conversation_id":null,"timezone_offset_min":-480}`)

// FetchAccountQuota 拉取账号远程图片额度（对等 Python refresh_accounts 单号探测）。
// 探测链路：POST /backend-api/conversation/init
// 返回 401 → OK=false（token 失效，调用方按验活失败语义处理）。
func (b *Backend) FetchAccountQuota(ctx context.Context) (AccountQuota, error) {
	headers := b.RequestHeaders(conversationInitPath, map[string]string{
		"Accept":       "application/json",
		"Content-Type": "application/json",
	})
	reqCtx, cancel := context.WithTimeout(ctx, 25*time.Second)
	defer cancel()
	resp, body, err := b.doJSONRequest(reqCtx, fhttp.MethodPost, b.BaseURL+conversationInitPath, headers, conversationInitBody)
	if err != nil {
		return AccountQuota{}, err
	}
	if err := ensureOK(resp.StatusCode, resp.Header.Get("Retry-After"), body, conversationInitPath, "account"); err != nil {
		return AccountQuota{}, err
	}
	return parseAccountQuota(body)
}

// parseAccountQuota 解析 conversation/init 响应（容错：上游字段形状随版本漂移）。
// 已知形状（2026-09 实测）：
//
//	{"limits_progress":[{"feature_name":"image_gen","remaining":25,
//	 "reset_after":"2026-10-08T00:00:00Z"}, ...]}
//
// 未命中 image_gen 项或形状不识别 → OK=true + Quota=0（quota_unknown 语义，不报错）。
func parseAccountQuota(body []byte) (AccountQuota, error) {
	var raw map[string]any
	if err := json.Unmarshal(body, &raw); err != nil {
		return AccountQuota{}, fmt.Errorf("parse quota response: %w", err)
	}
	out := AccountQuota{OK: true}
	if plan := quotaPlanFrom(raw); plan != "" {
		out.PlanType = plan
	}
	if q, ok := quotaFromLimitsProgress(raw); ok {
		out.Quota = q
		return out, nil
	}
	// 形状不识别：额度未知但账号验活通过（quota_unknown 语义），不报错
	out.Quota = 0
	return out, nil
}

// quotaFromLimitsProgress 从 limits_progress[] 找 feature_name=image_gen 项的 remaining。
func quotaFromLimitsProgress(raw map[string]any) (int, bool) {
	arr, ok := raw["limits_progress"].([]any)
	if !ok {
		return 0, false
	}
	for _, item := range arr {
		m, ok := item.(map[string]any)
		if !ok {
			continue
		}
		feat, _ := m["feature_name"].(string)
		if !strings.EqualFold(strings.TrimSpace(feat), "image_gen") {
			continue
		}
		remaining := quotaFloat(m, "remaining")
		if remaining < 0 {
			remaining = 0
		}
		return int(remaining), true
	}
	return 0, false
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
