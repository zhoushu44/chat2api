// Package sse 提供基于 tls-client 响应体的 SSE 流式解析。
// 对等 Python utils/helper.py 的 iter_sse_payloads / stream cancel，
// 但为事件驱动设计：终止标记出现后回调即刻触发，无线程泵调度延迟。
package sse

import (
	"bufio"
	"bytes"
	"context"
	"errors"
	"io"
	"strings"
	"sync"
	"time"
)

var (
	scannerBufPool = sync.Pool{New: func() any { b := make([]byte, 64*1024); return &b }}
	linesPool      = sync.Pool{New: func() any { s := make([]string, 0, 8); return &s }}
	bufferPool     = sync.Pool{New: func() any { return &bytes.Buffer{} }}
)

// Event 单个 SSE 事件。
type Event struct {
	Data  string
	Name  string // event: 字段（chatgpt2api 官网流主要为 data 帧）
	At    time.Time
}

// TerminalMarker SSE 流内检测到的"本轮已完成"标记。
// 对等 Python openai_backend_api._is_image_stream_terminal_payload：
// finished_successfully + is_complete 出现即离开 SSE 阶段，不必等连接关闭。
type TerminalMarker struct {
	ConversationID string
	FileIDs        []string // 流内已解析出的 asset pointer（提前拿，不等轮询）
}

// Scanner SSE 流读取器。
type Scanner struct {
	reader    io.Reader
	timeout   time.Duration
	onPayload func(payload string) (terminal bool, marker TerminalMarker)
}

// New 创建 Scanner。onPayload 返回 terminal=true 时立即停止读取。
func New(reader io.Reader, streamTimeout time.Duration, onPayload func(string) (bool, TerminalMarker)) *Scanner {
	return &Scanner{reader: reader, timeout: streamTimeout, onPayload: onPayload}
}

// Run 阻塞读取直至流结束、终止标记或超时。
// 返回终止标记（若触发）或错误。
func (s *Scanner) Run(ctx context.Context) (TerminalMarker, error) {
	ctx, cancel := context.WithTimeout(ctx, s.timeout)
	defer cancel()

	pr, pw := io.Pipe()
	var once sync.Once
	stopRead := func() { once.Do(func() { pw.CloseWithError(errStopped) }) }

	// 读 goroutine：ctx 超时/取消时中断底层 reader（对等 Python 的 stream cancel）。
	go func() {
		<-ctx.Done()
		stopRead()
	}()
	go func() {
		_, _ = io.Copy(pw, s.reader)
		stopRead()
	}()

	bufPtr := scannerBufPool.Get().(*[]byte)
	defer scannerBufPool.Put(bufPtr)
	sc := bufio.NewScanner(pr)
	sc.Buffer(*bufPtr, 16*1024*1024) // 复用 64KB 初始，上限 16MB

	var marker TerminalMarker
	linesPtr := linesPool.Get().(*[]string)
	dataLines := *linesPtr
	defer func() { *linesPtr = dataLines[:0]; linesPool.Put(linesPtr) }()
	flush := func() (bool, error) {
		if len(dataLines) == 0 {
			return false, nil
		}
		// 池化 Join：用 bytes.Buffer 避免 strings.Join 多次分配
		b := bufferPool.Get().(*bytes.Buffer)
		b.Reset()
		for i, l := range dataLines {
			if i > 0 {
				b.WriteByte('\n')
			}
			b.WriteString(l)
		}
		payload := b.String()
		bufferPool.Put(b)
		dataLines = dataLines[:0]
		if s.onPayload == nil {
			return false, nil
		}
		terminal, m := s.onPayload(payload)
		if terminal {
			marker = m
			return true, errStopped
		}
		return false, nil
	}

	for sc.Scan() {
		line := sc.Text()
		switch {
		case line == "":
			// 空行 = 事件边界
			if done, _ := flush(); done {
				return marker, nil
			}
		case strings.HasPrefix(line, "data:"):
			dataLines = append(dataLines, strings.TrimPrefix(strings.TrimPrefix(line, "data:"), " "))
		case strings.HasPrefix(line, "event:"):
			// 官网流偶发 event 帧，暂存不处理
		}
		if ctx.Err() != nil {
			return marker, ctx.Err()
		}
	}
	_, _ = flush()
	if e := ctx.Err(); e != nil {
		return marker, e
	}
	return marker, nil
}

var errStopped = errors.New("sse: stopped by terminal marker")
