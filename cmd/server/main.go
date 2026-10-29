// chatgpt2api-go：ChatGPT 官网逆向 API 网关（Go 版）。
// 对等 Python v2.7.0；核心目标：单图端到端 ≤10s，万级并发不退化。
//
// 启动：./chatgpt2api-go [-config config.json] [-addr :3000]
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"log"
	"net/http"
	_ "net/http/pprof"
	"os"
	"os/signal"
	"runtime"
	"syscall"
	"time"

	"chatgpt2api/internal/account"
	"chatgpt2api/internal/account/oauth"
	"chatgpt2api/internal/api"
	"chatgpt2api/internal/autotune"
	"chatgpt2api/internal/backend"
	"chatgpt2api/internal/config"
	"chatgpt2api/internal/provider"
	"chatgpt2api/internal/refresh"
	"chatgpt2api/internal/register"
	"chatgpt2api/internal/scheduler"
)

func main() {
	autotune.Tune()
	// pprof 常开，验证 10s 预算与无泄漏
	go func() {
		runtime.SetBlockProfileRate(10000)
		runtime.SetMutexProfileFraction(5)
		_ = http.ListenAndServe("127.0.0.1:6060", nil)
	}()
	cfgPath := flag.String("config", "config.json", "配置文件路径")
	addr := flag.String("addr", ":3000", "监听地址")
	flag.Parse()

	cfg, err := config.Load(*cfgPath)
	if err != nil {
		log.Fatalf("load config: %v", err)
	}
	if cfg.AuthKey == "" {
		log.Printf("WARNING: auth-key 未配置，/v1 与 /api 接口无鉴权")
	}
	provider.LoadAll()
	log.Printf("[provider] 已加载 %d mailbox / %d proxy / %d captcha 定义", len(provider.ListDefinitions(provider.TypeMailbox)), len(provider.ListDefinitions(provider.TypeProxy)), len(provider.ListDefinitions(provider.TypeCaptcha)))

	// P0.1 服务树组装：账号持久化+号池+日志+任务+编排（/v1 真实链路）
	srv := api.NewServer(cfg)

	regSvc := register.NewWithDir(cfg.DataDir)
	srv.Register = regSvc
	// 启动每日 401 验活调度器，对齐 abai core/scheduler.py；探针用 backend /me
	sched := scheduler.New(srv.Pool, cfg.Scheduler.Hour, cfg.Scheduler.Concurrency, cfg.Scheduler.Timezone, cfg.Scheduler.Enabled)
	sched.Svc = srv.Accounts
	sched.CheckValid = func(a *account.Account) bool {
		acctCtx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		be, err := backend.NewBackend(a.Token, a.FP, cfg.EffectiveProxy())
		if err != nil {
			return false
		}
		return be.VerifyToken(acctCtx) == nil
	}
	// Relogin 钩子 = 额度探测复活（21.0 refresh.go 的机制）。
	// 不是真的重新登录，而是 POST /backend-api/conversation/init 探测图片额度：
	// 能通就证明 token 仍有效，账号复活；只有探测也失败才判真死号。
	sched.Relogin = func(a *account.Account) (string, bool) {
		acctCtx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		be, err := backend.NewBackend(a.Token, a.FP, cfg.EffectiveProxy())
		if err != nil {
			return "", false
		}
		q, err := be.FetchAccountQuota(acctCtx)
		if err != nil || !q.OK {
			return "", false // 探测失败 = 真死号
		}
		// 探测成功：账号仍存活，回写额度并复活（refresh.go 的 StatusDisabled → Normal 由调度器处理）
		a.Quota = q.Quota
		if q.PlanType != "" {
			a.PlanType = q.PlanType
		}
		return a.Token, true // token 未变，但账号已证明存活
	}
	// Recover 钩子 = 密码+TOTP 协议登录恢复（22.0 恢复，每日 03:00 群验时使用）。
	// 与 Relogin 的区别：Relogin 是「探测能通就复活」，Recover 是「用密码+TOTP
	// 真正重新登录拿新 AT」。优先级：有密码+TOTP 的账号先走 Recover。
	sched.RecoveryEnabled = true
	sched.Recover = func(a *account.Account) (newToken, newSession string, err error) {
		if a.Password == "" || a.TOTPSecret == "" {
			return "", "", fmt.Errorf("缺少密码或 TOTP secret，无法协议恢复")
		}
		result, err := oauth.LoginWithPassword(a.Email, a.Password, a.TOTPSecret, cfg.EffectiveProxy(), func(msg string) {
			log.Printf("[recover] %s: %s", a.Email, msg)
		})
		if err != nil {
			return "", "", err
		}
		return result.AccessToken, result.SessionToken, nil
	}
	sched.Start()
	defer sched.Stop()
	// 注入路由：账号页「每日验活/协议恢复」开关与自动清理共用同一个调度器实例。
	srv.Scheduler = sched
	sched.SetAutoRemoveInvalid(cfg.AutoRemoveInvalidAccounts)

	// 启动额度周期同步（21.0 refresh.go 的 RunPeriodic）。
	// 定期探测所有账号的图片额度，能通就复活「失效」和「待重登」账号——
	// 这就是「每日重新登录能救活死号」的持续保障机制。
	refreshSvc := refresh.NewService(srv.Accounts, srv.Pool, cfg.EffectiveProxy())
	refreshInterval := 60 // 分钟，默认每小时
	if cfg.RefreshAccountMin > 0 {
		refreshInterval = cfg.RefreshAccountMin
	}
	refreshSvc.RunPeriodic(context.Background(), refreshInterval)
	log.Printf("[refresh] 周期额度同步已启动，间隔 %d 分钟（失效/待重登账号探测成功自动复活）", refreshInterval)

	r := srv.NewRouter()
	log.Printf("chatgpt2api-go listening on %s (storage=%s data=%s accounts=%d) GOMAXPROCS=%d auto_refill=%v", *addr, cfg.StorageType, cfg.DataDir, len(srv.Accounts.List()), runtime.GOMAXPROCS(0), regSvc.GetConfig().AutoRefill)

	// OPT-6 启动预热（后台，不阻塞监听）：号池建连 + bootstrap，首请求省 ~2-4s。
	go func() {
		ctx, cancel := context.WithTimeout(context.Background(), 3*time.Minute)
		defer cancel()
		srv.Warmup(ctx)
	}()

	// P0.6 优雅退出：信号触发 Shutdown，flush defer（此前 r.Run() 阻塞且 log.Fatal 跳过 defer）
	httpSrv := &http.Server{Addr: *addr, Handler: r}
	go func() {
		if err := httpSrv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Fatalf("listen: %v", err)
		}
	}()
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit
	log.Printf("shutting down (grace period 10s)...")
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := httpSrv.Shutdown(ctx); err != nil {
		log.Printf("shutdown: %v", err)
	}
	// 释放服务资源（logsvc 落盘句柄、metrics flush）
	srv.Close()
	log.Printf("bye")
}
