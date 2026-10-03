package admin

import (
	"encoding/json"
	"io"
	"net/http"
	"strconv"
	"strings"

	"chatgpt2api/internal/account"
	"chatgpt2api/internal/refresh"

	"github.com/gin-gonic/gin"
)

type AccountsHandler struct {
	Accounts *account.Service
	Pool     *account.Pool
	// Refresh 账号额度刷新服务（nil 时 refresh 路由返回 503）。
	Refresh *refresh.Service
}

func (h *AccountsHandler) Register(r *gin.RouterGroup) {
	r.GET("/accounts", h.List)
	r.POST("/accounts", h.Create)
	r.PUT("/accounts/:id", h.Update)
	r.DELETE("/accounts/:id", h.Delete)
	r.GET("/accounts/stats", h.Stats)
	r.POST("/accounts/check", h.Check)
	// 账号刷新：POST 启动（返回 progress_id），GET progress 轮询（前端「刷新账号信息和额度」按钮）
	r.POST("/accounts/refresh", h.RefreshAccounts)
	r.GET("/accounts/refresh/progress/:id", h.RefreshProgress)
	// 账号清理：preview 只统计，run 真正删除（控制台「自动移除异常/限流账号」开关调用）
	r.POST("/accounts/cleanup/preview", h.CleanupPreview)
	r.POST("/accounts/cleanup/run", h.CleanupRun)
}

func (h *AccountsHandler) List(c *gin.Context) {
	search := strings.TrimSpace(c.Query("search"))
	hasRefresh := c.Query("has_refresh_token")
	is401 := c.Query("is_401")
	only401 := c.Query("only_401") == "true" || is401 == "1" || is401 == "true"
	onlyRefresh := hasRefresh == "1" || hasRefresh == "true"
	page, _ := strconv.Atoi(c.DefaultQuery("page", "1"))
	pageSize, _ := strconv.Atoi(c.DefaultQuery("page_size", "20"))
	if page < 1 {
		page = 1
	}
	if pageSize < 1 || pageSize > 100 {
		pageSize = 20
	}
	// 兼容 Service 和 Pool 两种存储
	var all []*account.Account
	if h.Pool != nil {
		// 从 Pool 取（需遍历 shards，此处简化：通过 Service List 若存在）
		if h.Accounts != nil {
			all = h.Accounts.List()
		}
	} else if h.Accounts != nil {
		all = h.Accounts.List()
	}
	// 过滤
	filtered := make([]*account.Account, 0, len(all))
	for _, a := range all {
		if search != "" && !strings.Contains(strings.ToLower(a.Email), strings.ToLower(search)) {
			continue
		}
		if onlyRefresh && a.RefreshToken == "" {
			continue
		}
		if only401 && a.ValidityStatus != "invalid" {
			// 401 标记为 invalid
			continue
		}
		filtered = append(filtered, a)
	}
	total := len(filtered)
	start := (page - 1) * pageSize
	end := start + pageSize
	if start > total {
		start = total
	}
	if end > total {
		end = total
	}
	pageItems := filtered[start:end]
	// 映射为前端期望的 AccountListItem（键集对齐 Python _account_for_api 全量字典，
	// 前端 Accounts 页重度引用 access_token/source_type/quota/status/type 等键）
	items := make([]map[string]any, 0, len(pageItems))
	for i, a := range pageItems {
		items = append(items, map[string]any{
			"id":                      i + start + 1,
			"email":                   a.Email,
			"access_token":            a.Token,
			"token":                   a.Token,
			"refresh_token":           a.RefreshToken,
			"password":                "", // 不暴露明文
			"has_password":            a.Password != "",
			"has_totp":                a.TOTPSecret != "",
			"recoverable":             a.Password != "" && a.TOTPSecret != "",
			"has_refresh_token":       a.RefreshToken != "",
			"refresh_token_status":    map[bool]string{true: "valid", false: "missing"}[a.RefreshToken != ""],
			"type":                    a.Type,
			"plan_type":               a.PlanType,
			"source_type":             a.SourceType,
			"status":                  a.Status,
			"quota":                   a.Quota,
			"quota_unknown":           a.QuotaUnknown,
			"pending_auth_scope":      a.PendingAuthScope,
			"user_id":                 "",
			"proxy":                   "",
			"chatimage_invalid_401":   a.ValidityStatus == "invalid",
			"chatimage_import_status": "not_imported",
			"validity_status":         a.ValidityStatus,
			"lifecycle_status":        a.LifecycleStatus,
			"plan_state":              a.PlanState,
			"checked_at":              a.CheckedAt,
			"created_at":              "",
		})
	}
	c.JSON(http.StatusOK, gin.H{
		"items":      items,
		"data":       items,
		"total":      total,
		"page":       page,
		"page_size":  pageSize,
		"total_page": (total + pageSize - 1) / pageSize,
	})
}

func (h *AccountsHandler) Stats(c *gin.Context) {
	var all []*account.Account
	if h.Accounts != nil {
		all = h.Accounts.List()
	}
	alive := 0
	for _, a := range all {
		if a.ValidityStatus == "valid" || a.ValidityStatus == "" {
			alive++
		}
	}
	c.JSON(http.StatusOK, gin.H{
		"platform":                     "chatgpt",
		"alive_accounts":               alive,
		"historical_registered_emails": len(all),
		"survival_rate": func() float64 {
			if len(all) == 0 {
				return 0
			}
			return float64(alive) / float64(len(all))
		}(),
	})
}

func (h *AccountsHandler) Check(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"ok": true, "message": "check queued"})
}

// Create 兼容两种请求：
//  1. 单账号：{"token": "...", "email": "..."}（旧用法，原样响应账号对象）
//  2. 批量导入：{"tokens": [...], "accounts": [{access_token, email, type, source_type}]}
//     返回 {added, skipped, refreshed, errors}，供 RegiForge auto-import 与前端批量导入使用。
func (h *AccountsHandler) Create(c *gin.Context) {
	raw, err := io.ReadAll(c.Request.Body)
	if err != nil {
		c.JSON(400, gin.H{"error": err.Error()})
		return
	}
	var probe struct {
		Tokens   []string `json:"tokens"`
		Accounts []any    `json:"accounts"`
	}
	if json.Unmarshal(raw, &probe) == nil && (len(probe.Tokens) > 0 || len(probe.Accounts) > 0) {
		h.batchCreate(c, raw)
		return
	}
	var single account.Account
	if err := json.Unmarshal(raw, &single); err != nil {
		c.JSON(400, gin.H{"error": err.Error()})
		return
	}
	if h.Accounts != nil {
		_ = h.Accounts.Add(&single)
	}
	if h.Pool != nil {
		h.Pool.Add(&single)
	}
	c.JSON(http.StatusOK, single)
}

// batchCreate 处理批量导入：{accounts: [{access_token, email, type, source_type}]}
// 或 {tokens: ["sk-..."]}。重复 token 跳过并计数。
func (h *AccountsHandler) batchCreate(c *gin.Context, raw []byte) {
	var batch struct {
		Tokens   []string         `json:"tokens"`
		Accounts []map[string]any `json:"accounts"`
	}
	if err := json.Unmarshal(raw, &batch); err != nil {
		c.JSON(400, gin.H{"error": err.Error()})
		return
	}
	added, skipped, refreshed := 0, 0, 0
	var errors []map[string]any

	// accounts 字段名兼容 access_token/token
	field := func(m map[string]any, keys ...string) string {
		for _, k := range keys {
			if s, ok := m[k].(string); ok {
				return s
			}
		}
		return ""
	}

	addOne := func(token, email, typ, sourceType, password, totpSecret, sessionToken string) {
		token = strings.TrimSpace(token)
		if token == "" {
			skipped++
			return
		}
		a := &account.Account{
			Token:      token,
			Email:      email,
			Type:       account.NormalizeAccountType(typ),
			SourceType: account.NormalizeSourceType(sourceType),
			// 恢复凭据：AT 失效时走「邮箱+密码+TOTP」协议登录恢复（不等邮箱 OTP）
			Password:     strings.TrimSpace(password),
			TOTPSecret:   strings.TrimSpace(totpSecret),
			SessionToken: strings.TrimSpace(sessionToken),
			// 注册/导入的 token 刚获取即可用；未检测前避免被 Pool.Available() 判为不可用
			Status: account.StatusNormal,
		}
		if h.Accounts != nil {
			if err := h.Accounts.Add(a); err != nil {
				errors = append(errors, map[string]any{"token": token[:8], "error": err.Error()})
				return
			}
		}
		if h.Pool != nil {
			h.Pool.Add(a)
		}
		added++
	}

	for _, tok := range batch.Tokens {
		addOne(tok, "", "Plus", "web", "", "", "")
	}
	for _, m := range batch.Accounts {
		typ := field(m, "type")
		if typ == "" {
			typ = "Plus"
		}
		src := field(m, "source_type")
		if src == "" {
			src = "web"
		}
		addOne(
			field(m, "access_token", "token"),
			field(m, "email"),
			typ,
			src,
			field(m, "password"),
			field(m, "totp_secret"),
			field(m, "session_token"),
		)
	}
	c.JSON(http.StatusOK, gin.H{
		"added": added, "skipped": skipped, "refreshed": refreshed,
		"errors": errors,
	})
}
func (h *AccountsHandler) Update(c *gin.Context) {
	id := c.Param("id")
	var a account.Account
	_ = c.ShouldBindJSON(&a)
	a.ID = id
	if h.Accounts != nil {
		_ = h.Accounts.Add(&a)
	}
	if h.Pool != nil {
		h.Pool.Add(&a)
	}
	c.JSON(http.StatusOK, a)
}
func (h *AccountsHandler) Delete(c *gin.Context) {
	id := c.Param("id")
	// 先取 token 以便同步移出号池（P2.6c）
	var token string
	if h.Accounts != nil {
		if a, ok := h.Accounts.Get(id); ok && a != nil {
			token = a.Token
		}
		_ = h.Accounts.Delete(id)
	}
	if h.Pool != nil && token != "" {
		h.Pool.Remove(token)
	}
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

// accountCleanupRequest 账号清理请求，字段名与前端 settingsApi 一致。
type accountCleanupRequest struct {
	AutoRemoveInvalid     bool `json:"auto_remove_invalid_accounts"`
	AutoRemoveRateLimited bool `json:"auto_remove_rate_limited_accounts"`
}

// accountCleanupResult 账号清理结果，字段名与前端 AccountCleanupResult 一致。
type accountCleanupResult struct {
	TotalRemoved  int      `json:"total_removed"`
	Invalid       int      `json:"invalid"`
	RateLimited   int      `json:"rate_limited"`
	RemovedEmails []string `json:"removed_emails"`
}

// CleanupPreview 只统计匹配账号数量，不删除。
func (h *AccountsHandler) CleanupPreview(c *gin.Context) { h.cleanup(c, true) }

// CleanupRun 删除匹配账号（同步移出号池）。
func (h *AccountsHandler) CleanupRun(c *gin.Context) { h.cleanup(c, false) }

// cleanup 按开关统计/移除账号。
// invalid：鉴权失效（status=失效 或 validity_status=invalid）。
// rate_limited：账号被标记为限流（status=限流）。
// 注意：不能用 quota 判定——配额是导入时的快照，运行期从不刷新，
// 健康账号同样是 quota=0/quota_unknown=false，据此会误删全部账号。
// 同一账号只归入一个分类，避免重复计数。
func (h *AccountsHandler) cleanup(c *gin.Context, dryRun bool) {
	var req accountCleanupRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{
			"message": "清理报文不是合法的 JSON 对象: " + err.Error(),
			"type":    "invalid_request_error",
		}})
		return
	}
	result := accountCleanupResult{RemovedEmails: []string{}}
	var targets []*account.Account
	if h.Accounts != nil {
		for _, a := range h.Accounts.List() {
			if a == nil {
				continue
			}
			if a.Status == account.StatusDisabled || a.ValidityStatus == "invalid" {
				if req.AutoRemoveInvalid {
					result.Invalid++
					targets = append(targets, a)
				}
				continue
			}
			if a.Status == account.StatusLimited && req.AutoRemoveRateLimited {
				result.RateLimited++
				targets = append(targets, a)
			}
		}
	}
	result.TotalRemoved = len(targets)
	for _, a := range targets {
		if a.Email != "" {
			result.RemovedEmails = append(result.RemovedEmails, a.Email)
		}
		if dryRun {
			continue
		}
		if h.Pool != nil && a.Token != "" {
			h.Pool.Remove(a.Token)
		}
		id := a.ID
		if id == "" {
			id = a.Email
		}
		if h.Accounts != nil && id != "" {
			_ = h.Accounts.Delete(id)
		}
	}
	c.JSON(http.StatusOK, result)
}

// RefreshAccounts 启动账号额度刷新（前端「刷新账号信息和额度」按钮）。
// body: {"access_tokens": [...]}（空数组/缺省 = 全部）→ {progress_id}
// 对等 Python POST /api/accounts/refresh 契约。
func (h *AccountsHandler) RefreshAccounts(c *gin.Context) {
	if h.Refresh == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": gin.H{
			"message": "account refresh service unavailable",
			"type":    "api_error", "code": "service_unavailable",
		}})
		return
	}
	var body struct {
		AccessTokens []string `json:"access_tokens"`
	}
	_ = c.ShouldBindJSON(&body) // 空 body 也合法（全量刷新）
	tokens := make([]string, 0, len(body.AccessTokens))
	for _, t := range body.AccessTokens {
		if t = strings.TrimSpace(t); t != "" {
			tokens = append(tokens, t)
		}
	}
	progressID, err := h.Refresh.RefreshAll(c.Request.Context(), tokens)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{
			"message": err.Error(), "type": "invalid_request_error", "code": "refresh_failed",
		}})
		return
	}
	c.JSON(http.StatusOK, gin.H{"progress_id": progressID})
}

// RefreshProgress 轮询刷新进度（前端 refreshAndPoll 契约）。
// 返回 {total, processed, done, error?, status_counts?, total_quota?, result?}。
func (h *AccountsHandler) RefreshProgress(c *gin.Context) {
	id := strings.TrimSpace(c.Param("id"))
	p := refresh.GetProgress(id)
	if p == nil {
		// 已清理/不存在：视为完成（前端据此停止轮询）
		c.JSON(http.StatusOK, gin.H{"total": 0, "processed": 0, "done": true})
		return
	}
	out := refresh.ProgressJSON(p)
	// result 字段：对齐前端 AccountRefreshProgress.result 形状
	out["result"] = gin.H{
		"refreshed": p.Refreshed,
		"errors":    p.Errors,
		"items":     p.Items,
	}
	c.JSON(http.StatusOK, out)
}
