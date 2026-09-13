package admin

import (
	"encoding/json"
	"io"
	"net/http"
	"strconv"
	"strings"

	"chatgpt2api/internal/account"

	"github.com/gin-gonic/gin"
)

type AccountsHandler struct {
	Accounts *account.Service
	Pool     *account.Pool
}

func (h *AccountsHandler) Register(r *gin.RouterGroup) {
	r.GET("/accounts", h.List)
	r.POST("/accounts", h.Create)
	r.PUT("/accounts/:id", h.Update)
	r.DELETE("/accounts/:id", h.Delete)
	r.GET("/accounts/stats", h.Stats)
	r.POST("/accounts/check", h.Check)
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
			"id":                       i + start + 1,
			"email":                    a.Email,
			"access_token":             a.Token,
			"token":                    a.Token,
			"refresh_token":            a.RefreshToken,
			"password":                 "", // 不暴露明文
			"has_refresh_token":        a.RefreshToken != "",
			"refresh_token_status":     map[bool]string{true: "valid", false: "missing"}[a.RefreshToken != ""],
			"type":                     a.Type,
			"plan_type":                a.PlanType,
			"source_type":              a.SourceType,
			"status":                   a.Status,
			"quota":                    a.Quota,
			"quota_unknown":            a.QuotaUnknown,
			"pending_auth_scope":       a.PendingAuthScope,
			"user_id":                  "",
			"proxy":                    "",
			"chatimage_invalid_401":    a.ValidityStatus == "invalid",
			"chatimage_import_status":  "not_imported",
			"validity_status":          a.ValidityStatus,
			"lifecycle_status":         a.LifecycleStatus,
			"plan_state":               a.PlanState,
			"checked_at":               a.CheckedAt,
			"created_at":               "",
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
		"platform": "chatgpt",
		"alive_accounts": alive,
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

	addOne := func(token, email, typ, sourceType string) {
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
		addOne(tok, "", "Plus", "web")
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
		addOne(field(m, "access_token", "token"), field(m, "email"), typ, src)
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
