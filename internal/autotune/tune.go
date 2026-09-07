package autotune

import (
	"runtime"
)

// Tune 设置 GOMAXPROCS = CPU*2，上限 32，适配容器 cgroup
// 对等 go.uber.org/automaxprocs 轻量实现，无额外依赖
func Tune() {
	n := runtime.NumCPU() * 2
	if n > 32 {
		n = 32
	}
	if n < 4 {
		n = 4
	}
	runtime.GOMAXPROCS(n)
}
