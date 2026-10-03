#!/bin/bash
# 第二十六轮：量化 usque 引擎死亡率 —— 全量 100 引擎快速探测
set -u

echo "===== A. 全量 usque 引擎（20000-20099）快速 TCP+出口探测 ====="
OK=0; SLOW=0; DEAD=0; TIMEOUT=0
DEAD_LIST=""
for idx in $(seq 0 99); do
  P=$((20000 + idx))
  R=$(timeout 10 curl -s --socks5-hostname "127.0.0.1:$P" -o /dev/null -w "%{http_code} %{time_total}" https://sentinel.openai.com/backend-api/sentinel/frame.html 2>/dev/null)
  RC=$?
  CODE=$(echo "$R" | awk '{print $1}')
  T=$(echo "$R" | awk '{print $2}')
  if [ $RC -eq 124 ]; then
    TIMEOUT=$((TIMEOUT+1)); DEAD_LIST="$DEAD_LIST $idx"
  elif [ "$CODE" = "200" ]; then
    # 判断快慢
    FAST=$(echo "$T" | cut -d. -f1)
    if [ "${FAST:-0}" -lt 3 ]; then OK=$((OK+1)); else SLOW=$((SLOW+1)); fi
  else
    DEAD=$((DEAD+1)); DEAD_LIST="$DEAD_LIST $idx"
  fi
done
echo "结果: 快(<3s)=$OK | 慢(3-10s)=$SLOW | 错误=$DEAD | 超时挂死=$TIMEOUT"
echo "死/挂引擎清单:$DEAD_LIST"
