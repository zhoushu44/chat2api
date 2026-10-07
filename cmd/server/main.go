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
	"sync"
	"syscall"
	"time"

	"chatgpt2api/internal/account"
	"chatgpt2api/internal/account/oauth"
	"chatgpt2api/internal/api"
	"chatgpt2api/internal/autotune"
	"chatgpt2api/internal/backend"
	"chatgpt2api/internal/config"
	"chatgpt2api/internal/proxy"
	"chatgpt2api/internal/provider"
	"chatgpt2api/internal/refresh"
	"chatgpt2api/internal/register"
	"chatgpt2api/internal/scheduler"
	"chatgpt2api/internal/settings"
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
	// 验活探测（三态语义）：nil=活 / ErrVerifyNetwork=网络错误跳过 / 其他=确认失效（401/403）。
	// 历史 bug：任何错误（含 DNS 超时）都被判死，一次误杀 93 号。现在只有上游明确
	// 返回 401/403 才算真失效；网络类错误重试一次后仍失败则归为「无法确认」跳过。
	sched.CheckValid = func(a *account.Account) error {
		probe := func() error {
			acctCtx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
			defer cancel()
			be, err := backend.NewBackend(a.Token, a.FP, cfg.EffectiveProxy())
			if err != nil {
				return fmt.Errorf("%w: %v", scheduler.ErrVerifyNetwork, err)
			}
			return be.VerifyToken(acctCtx)
		}
		err := probe()
		if err == nil {
			return nil
		}
		// 真 401/403：确认失效，原样返回
		var ue *backend.UpstreamHTTPError
		if errors.As(err, &ue) && (ue.StatusCode == 401 || ue.StatusCode == 403) {
			return err
		}
		// 网络类错误：重试一次（Fix C，防瞬断抖动）
		err2 := probe()
		if err2 == nil {
			return nil
		}
		var ue2 *backend.UpstreamHTTPError
		if errors.As(err2, &ue2) && (ue2.StatusCode == 401 || ue2.StatusCode == 403) {
			return err2
		}
		return fmt.Errorf("%w: %v（重试后仍网络错误）", scheduler.ErrVerifyNetwork, err2)
	}
	// D 段：401 验活失败后的协议登录恢复（邮箱+密码+TOTP，不等邮箱 OTP）
	sched.RecoveryEnabled = cfg.Scheduler.RecoveryEnabled
	sched.RecoverAttempts = 3 // 网络约 5% 瞬断，重试防「好账号被一次抖动误杀」
	// 自动移除不可恢复账号：控制台「系统设置 → 自动移除异常账号」开关（settings.json 持久化）
	if v, ok := settings.NewStore(cfg.DataDir).Snapshot()["auto_remove_invalid_accounts"].(bool); ok {
		sched.AutoRemoveInvalid = v
		log.Printf("[Scheduler] 自动移除不可恢复账号：%v", v)
	}
	// 每次重试前换出口：代理池优先，回退全局代理（坏出口直接跳过）。
	// 轮换结果通过闭包变量传给 Recover，保证「本轮选中的出口」被真正使用。
	var rotatedProxy string
	var rotatedMu sync.Mutex
	sched.RotateProxy = func() string {
		p := proxy.DefaultPool.GetNext("")
		if p == "" {
			p = cfg.EffectiveProxy()
		}
		rotatedMu.Lock()
		rotatedProxy = p
		rotatedMu.Unlock()
		return p
	}
	sched.Recover = func(a *account.Account) (string, string, error) {
		rotatedMu.Lock()
		pxy := rotatedProxy
		rotatedMu.Unlock()
		if pxy == "" {
			pxy = cfg.EffectiveProxy()
		}
		res, err := oauth.LoginWithPassword(a.Email, a.Password, a.TOTPSecret, pxy, func(s string) {
			log.Printf("[recovery] %s %s", a.Email, s)
		})
		if err != nil {
			return "", "", err
		}
		return res.AccessToken, res.SessionToken, nil
	}
	sched.Start()
	defer sched.Stop()
	// 账号页开关覆盖：持久化设置 > 配置文件默认
	if persisted, ok := scheduler.LoadPersistedEnabled(cfg.DataDir, cfg.Scheduler.Enabled); ok && persisted != sched.Enabled {
		sched.SetEnabled(persisted)
		log.Printf("[Scheduler] 已从持久化设置覆盖开关：%v", persisted)
	}
	// 注入到路由（/api/scheduler GET/PUT，账号页开关用）
	srv.Sched = sched

	// 账号额度周期同步（refresh_account_interval_minute 驱动，默认 60 分钟）：
	// 全量探测远程图片额度回写号池，修复「剩余额度」展示口径。
	refreshCtx, refreshCancel := context.WithCancel(context.Background())
	defer refreshCancel()
	refreshSvc := refresh.NewService(srv.Accounts, srv.Pool, cfg.EffectiveProxy())
	srv.Refresher = refreshSvc
	refreshSvc.RunPeriodic(refreshCtx, cfg.RefreshAccountMin)
	log.Printf("[refresh] 已启动周期额度同步，间隔 %d 分钟", cfg.RefreshAccountMin)

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
