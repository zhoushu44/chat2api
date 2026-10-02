package superres

import (
	"context"
	"fmt"
	"testing"
	"time"
)

// TestLiveTencentCOS 真实凭证连通性测试（非 CI；本地手动验证用）。
// 凭证来自服务器 /opt/image-super-resolution/.env（用户授权获取）。
// 跳过条件：环境变量 SUPERRES_LIVE_TEST 未设置。
func TestLiveTencentCOS(t *testing.T) {
	cfg := liveTestConfig(t)
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	png := buildTestPNG(t)
	dataURL := "data:image/png;base64," + base64Std(png)

	// 2 倍超分 + 校验成品尺寸真的放大了
	plan := &Plan{SourceSize: "1024x1024", Factor: 2, Target: &Size{W: 2048, H: 2048}}
	got := Enhance(ctx, cfg, plan, dataURL)
	if got == dataURL {
		t.Fatal("Enhance fell back to original — COS upload/super-resolution failed (see log above)")
	}
	if len(got) < 40 || got[:8] != "https://" {
		t.Fatalf("unexpected result: %.120s", got)
	}
	fmt.Printf("LIVE-OK 2x result URL: %s\n", got)
	if w, h := downloadImageSize(t, got); w != 128 || h != 128 {
		t.Errorf("2x super-resolution result = %dx%d, want 128x128 (64x64 source)", w, h)
	} else {
		fmt.Printf("LIVE-SIZE 2x: %dx%d (source 64x64)\n", w, h)
	}

	// 4 倍超分
	plan4 := &Plan{SourceSize: "512x512", Factor: 4, Target: &Size{W: 3840, H: 3840}}
	got4 := Enhance(ctx, cfg, plan4, dataURL)
	if got4 == dataURL {
		t.Fatal("Enhance 4x fell back to original (see log above)")
	}
	fmt.Printf("LIVE-OK 4x result URL: %s\n", got4)
	if w, h := downloadImageSize(t, got4); w != 256 || h != 256 {
		t.Errorf("4x super-resolution result = %dx%d, want 256x256 (64x64 source)", w, h)
	} else {
		fmt.Printf("LIVE-SIZE 4x: %dx%d (source 64x64)\n", w, h)
	}
}
