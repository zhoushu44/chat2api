package main

// 诊断工具：用单个账号的 email/password/totp 走一次协议登录，打印每步结果。
// 用途：区分「密码错」与「账号被停用」，二者在上游返回的 code 不同。
//
// 用法（容器内）：
//   go run ./cmd/pwcheck -email x@y -password '...' -totp '...'

import (
	"flag"
	"fmt"
	"os"

	"chatgpt2api/internal/account/oauth"
)

func main() {
	email := flag.String("email", "", "账号邮箱")
	password := flag.String("password", "", "密码")
	totp := flag.String("totp", "", "TOTP secret")
	proxy := flag.String("proxy", "", "代理（可选）")
	flag.Parse()
	if *email == "" || *password == "" {
		fmt.Println("需要 -email 和 -password")
		os.Exit(2)
	}
	res, err := oauth.LoginWithPassword(*email, *password, *totp, *proxy, func(msg string) {
		fmt.Println("[step]", msg)
	})
	if err != nil {
		fmt.Println("FAIL:", err.Error())
		os.Exit(1)
	}
	fmt.Printf("OK access_token_len=%d session_len=%d\n", len(res.AccessToken), len(res.SessionToken))
}
