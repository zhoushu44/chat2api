// Package api HTTP 路由层（gin）。
package api

import (
	"context"
	"net/http"
	"strings"

	"chatgpt2api/internal/account"
	"chatgpt2api/internal/api/admin"
	v1 "chatgpt2api/internal/api/v1"
	"chatgpt2api/internal/auth"
	"chatgpt2api/internal/config"
	"chatgpt2api/internal/filter"
	"chatgpt2api/internal/logsvc"
	"chatgpt2api/internal/mailbox"
	"chatgpt2api/internal/model"
	"chatgpt2api/internal/monitor/metrics"
	"chatgpt2api/internal/prompt"
	"chatgpt2api/internal/protocol"
	"chatgpt2api/internal/register"
	"chatgpt2api/internal/task"
	"chatgpt2api/internal/utils"

	"github.com/gin-gonic/gin"
)

// Server HTTP 服务：P0.1 服务树组装后的入口。
// Pool/Orch 为 nil 时 /v1 生图路由返回 503（不再返回 mock 假数据）。
type Server struct {
	Cfg      *config.Config
	Register *register.Service
	Mailbox  *mailbox.Service
	// P0.1 服务树（由 main.go / NewServer 组装注入）
	Accounts *account.Service       // 账号持久化（accounts.json）
	Pool     *account.Pool          // 号池（调度/冷却/刷新）
	LogSvc   *logsvc.Service        // 调用日志（环形缓冲）
	Tasks    *task.Service          // 异步任务持久化
	Prompts  *prompt.Service        // 提示词库
	Orch     *protocol.Orchestrator // 生图编排（/v1 真实链路）
	// P1.4 模型目录
	Catalog *model.Catalog
	// P1.7 仪表盘指标
	Metrics *metrics.Metrics
	// P2.6 多密钥鉴权
	Auth *auth.Service
	// P2.6c 账号 watcher
	Watcher *account.Watcher
}

// NewServer 按 config 组装完整服务树（P0.1）。
// 从 dataDir 加载账号持久化、任务持久化，构建号池与编排器。
func NewServer(cfg *config.Config) *Server {
	dataDir := "./data"
	if cfg != nil && cfg.DataDir != "" {
		dataDir = cfg.DataDir
	}
	accountsSvc := account.New(dataDir)
	pool := account.NewPool(nil, 0)
	// 已持久化账号载入号池
	for _, a := range accountsSvc.List() {
		pool.Add(a)
	}
	orch := protocol.NewOrchestrator(pool)
	orch.Accounts = accountsSvc // auth 失效除名落盘（watcher 同步移除）
	orch.Logger = logsvc.NewWithDir(dataDir, 1000)
	metSvc := metrics.NewWithDir(dataDir)
	orch.Metrics = metSvc
	if cfg != nil {
		orch.Config.Proxy = cfg.EffectiveProxy()
		orch.Config.MaxAttempts = cfg.Account.MaxAttempts
		orch.Config.Concurrency = cfg.Account.Concurrency
		// P2.7 sensitive_words → 内容过滤
		filter.SetCustomWords(cfg.SensitiveWords)
		// P2.8 BPE 缓存持久化到 dataDir
		utils.SetBPECacheDir(dataDir + "/tiktoken-cache")
	}
	authSvc := auth.NewWithDir(dataDir, "")
	if cfg != nil {
		authSvc = auth.NewWithDir(dataDir, cfg.AuthKey)
	}
	watcher := account.NewWatcher(accountsSvc, pool, 0)
	watcher.Start()
	s := &Server{
		Cfg:      cfg,
		Accounts: accountsSvc,
		Pool:     pool,
		LogSvc:   orch.Logger,
		Tasks:    task.New(dataDir),
		Prompts:  prompt.New(),
		Orch:     orch,
		Catalog:  model.New(),
		Metrics:  metSvc,
		Auth:     authSvc,
		Watcher:  watcher,
	}
	return s
}

// Warmup 启动预热（OPT-6）：号池建连 + bootstrap，首请求省 ~2-4s；nil 安全。
func (s *Server) Warmup(ctx context.Context) int {
	if s == nil || s.Orch == nil {
		return 0
	}
	return s.Orch.Warmup(ctx)
}

// Close 释放服务资源（logsvc 落盘句柄等），优雅退出与测试清理时调用。
func (s *Server) Close() {
	if s.Watcher != nil {
		s.Watcher.Stop()
	}
	if s.LogSvc != nil {
		_ = s.LogSvc.Close()
	}
	if s.Metrics != nil {
		_ = s.Metrics.Flush()
	}
}

func (s *Server) NewRouter() *gin.Engine {
	r := gin.New()
	r.Use(gin.Recovery())
	r.Use(s.cors())
	r.GET("/healthz", func(c *gin.Context) { c.Status(http.StatusOK) })
	v1g := r.Group("/v1", s.auth())
	{
		v1g.GET("/models", s.handleModels)
		v1g.POST("/images/generations", s.handleImageGenerations)
		v1g.POST("/images/edits", s.handleImageEdits)
		v1g.POST("/chat/completions", s.handleChatCompletions)
		v1g.POST("/responses", s.handleResponses)
		v1g.POST("/messages", s.handleMessages)
	}
	if s.Register == nil {
		dir := ""
		if s.Cfg != nil {
			dir = s.Cfg.DataDir
		}
		s.Register = register.NewWithDir(dir)
	}
	if s.Mailbox == nil {
		dir := ""
		if s.Cfg != nil {
			dir = s.Cfg.DataDir
		}
		s.Mailbox = mailbox.NewService(dir)
	}
	RegisterRegister(r.Group(""), s.Register)
	// R4.8 面板登录（对等 Python /auth/login + /auth/status）
	RegisterAuthPanel(r.Group(""), s)
	(&ProviderHandler{}).Register(r.Group("/api"))
	(&ProxyHandler{}).Register(r.Group("/api"))
	(&MailboxHandler{Service: s.Mailbox}).Register(r.Group("/api"))

	// P0.4 挂载面板路由（此前为死代码）
	adminGroup := r.Group("/api", s.adminAuth())
	// /api/register* 对等 Python require_admin（R3.10；兼容旧路径与 events 仍开放）
	RegisterRegisterAdmin(adminGroup.Group("/register"), s.Register)
	// P2.6 用户密钥管理
	if s.Auth != nil {
		RegisterAuthUsers(adminGroup, s.Auth)
	}
	if s.Accounts != nil {
		(&admin.AccountsHandler{Accounts: s.Accounts, Pool: s.Pool}).Register(adminGroup)
	}
	if s.Cfg != nil {
		(&admin.SystemHandler{Cfg: s.Cfg, Catalog: s.Catalog}).Register(adminGroup)
	}
	if s.Tasks != nil {
		RegisterImageTasks(adminGroup, s.Tasks)
	}
	if s.Prompts != nil {
		RegisterPrompts(adminGroup, s.Prompts)
	}
	// P1.7 /api/dashboard（对等 Python system.py 该端点）
	adminGroup.GET("/dashboard", s.handleDashboard)
	// P0.4 静态 SPA（web_dist embed，此前从未生效）
	s.RegisterStatic(r, nil)
	return r
}

// cors 对等 Python CORSMiddleware（全放开，浏览器面板跨域可用）。
func (s *Server) cors() gin.HandlerFunc {
	return func(c *gin.Context) {
		origin := c.GetHeader("Origin")
		if origin != "" {
			c.Header("Access-Control-Allow-Origin", origin)
			c.Header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
			c.Header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Api-Key")
			c.Header("Access-Control-Allow-Credentials", "true")
		}
		if c.Request.Method == http.MethodOptions {
			c.AbortWithStatus(http.StatusNoContent)
			return
		}
		c.Next()
	}
}

// auth /v1 鉴权（P2.6，对等 require_identity）：
// 主密钥直接放行；否则校验多密钥体系（任意 enabled 密钥放行）；无配置则放行。
func (s *Server) auth() gin.HandlerFunc {
	return func(c *gin.Context) {
		if s.Cfg == nil || s.Cfg.AuthKey == "" {
			// 无主密钥时仍校验多密钥（若有）；都没有则放行
			if s.Auth == nil {
				return
			}
		}
		token := s.requestToken(c)
		if token == "" {
			// 未带密钥：仅当完全无鉴权配置时放行
			if (s.Cfg == nil || s.Cfg.AuthKey == "") && (s.Auth == nil || len(s.Auth.ListKeys("")) == 0) {
				return
			}
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{
				"error": gin.H{"message": "API key required", "type": "invalid_request_error", "code": "invalid_api_key"},
			})
			return
		}
		if s.Cfg != nil && s.Cfg.AuthKey != "" && token == s.Cfg.AuthKey {
			c.Next()
			return
		}
		if s.Auth != nil && s.Auth.Authenticate(token) != nil {
			c.Next()
			return
		}
		// 无任何鉴权配置（主密钥空且无用户密钥）→ 放行，保持旧行为
		if (s.Cfg == nil || s.Cfg.AuthKey == "") && (s.Auth == nil || len(s.Auth.ListKeys("")) == 0) {
			c.Next()
			return
		}
		c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{
			"error": gin.H{"message": "Incorrect API key provided", "type": "invalid_request_error", "code": "invalid_api_key"},
		})
	}
}

// adminAuth /api 面板鉴权（P2.6，对等 require_admin）：主密钥或 admin 角色密钥。
func (s *Server) adminAuth() gin.HandlerFunc {
	return func(c *gin.Context) {
		token := s.requestToken(c)
		if token != "" {
			if s.Cfg != nil && s.Cfg.AuthKey != "" && token == s.Cfg.AuthKey {
				c.Next()
				return
			}
			if s.Auth != nil {
				if item := s.Auth.Authenticate(token); item != nil && item["role"] == "admin" {
					c.Next()
					return
				}
			}
		}
		if (s.Cfg == nil || s.Cfg.AuthKey == "") && (s.Auth == nil || len(s.Auth.ListKeys("")) == 0) {
			c.Next()
			return
		}
		c.AbortWithStatusJSON(http.StatusForbidden, gin.H{
			"error": gin.H{"message": "admin key required", "type": "invalid_request_error", "code": "invalid_admin_key"},
		})
	}
}

// requestToken 提取 Bearer/X-Api-Key（精确匹配，主密钥比较不用 HasPrefix）。
func (s *Server) requestToken(c *gin.Context) string {
	if token := bearerToken(c.GetHeader("Authorization")); token != "" {
		return token
	}
	return strings.TrimSpace(c.GetHeader("X-Api-Key"))
}

func bearerToken(h string) string {
	if len(h) > 7 && strings.EqualFold(h[:7], "Bearer ") {
		return strings.TrimSpace(h[7:])
	}
	return ""
}

func (s *Server) handleModels(c *gin.Context) { v1.HandleModels(c) }
func (s *Server) handleImageGenerations(c *gin.Context) {
	// P2.7 生图总开关（仅显式 image_generation.enabled=false 时 503；默认启用）
	if s.Cfg != nil && s.Cfg.ImageGeneration.ExplicitlyDisabled() {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": gin.H{
			"message": "image generation disabled by configuration",
			"type":    "api_error", "code": "service_unavailable",
		}})
		return
	}
	v1.HandleGenerationsWith(c, s.Orch)
}
func (s *Server) handleImageEdits(c *gin.Context)      { v1.HandleEditsWith(c, s.Orch) }
func (s *Server) handleChatCompletions(c *gin.Context) { v1.HandleChatCompletionsWith(c, s.Orch) }
func (s *Server) handleResponses(c *gin.Context)       { v1.HandleResponsesWith(c, s.Orch) }
func (s *Server) handleMessages(c *gin.Context)        { v1.HandleMessagesWith(c, s.Orch) }

// handleDashboard 仪表盘汇总（P1.7，对等 Python system.py /api/dashboard）。
// time_range: 24h（默认）| 7d | 30d；附带账号健康度。
func (s *Server) handleDashboard(c *gin.Context) {
	timeRange := c.DefaultQuery("time_range", "24h")
	if timeRange != "24h" && timeRange != "7d" && timeRange != "30d" {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"message": "invalid time_range", "type": "invalid_request_error", "code": "invalid_time_range"}})
		return
	}
	var summary map[string]any
	if s.Metrics != nil {
		summary = s.Metrics.Summary(timeRange)
	} else {
		summary = map[string]any{"time_range": timeRange, "labels": []string{}, "series": []any{}, "total": map[string]any{}}
	}
	// 账号健康度（对等 account_healthy：有活跃或不限额账号）
	active, total := 0, 0
	if s.Accounts != nil {
		for _, a := range s.Accounts.List() {
			total++
			if a.Status == account.StatusNormal {
				active++
			}
		}
	}
	healthy := active > 0
	status := "ok"
	if !healthy {
		status = "degraded"
	}
	c.JSON(http.StatusOK, gin.H{
		"status":         status,
		"healthy":        healthy,
		"account_active": active,
		"account_total":  total,
		"metrics":        summary,
	})
}
