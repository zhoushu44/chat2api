#!/bin/bash
echo "--- PID1 ---"; docker exec chatgpt2api-13 tr '\0' ' ' < /proc/1/cmdline 2>/dev/null; echo
echo "--- PID10 ---"; docker exec chatgpt2api-13 cat /proc/10/cmdline 2>/dev/null | tr '\0' ' '; echo
echo "--- procs ---"
docker exec chatgpt2api-13 ps -ef | grep -E 'chatgpt2api-go|uvicorn|oauth.test' | grep -v grep
echo "--- node count ---"
docker exec chatgpt2api-13 ps -ef | grep node | grep -v grep | wc -l
echo "--- node ppid breakdown ---"
docker exec chatgpt2api-13 ps -eo ppid,cmd | grep node | grep -v grep | awk '{print $1}' | sort | uniq -c
