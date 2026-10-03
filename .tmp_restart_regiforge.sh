#!/bin/bash
set -u
echo "=== 重启容器（regiforge uvicorn 由 supervisor 管理，需要容器重启或重启进程） ==="
# 杀 uvicorn 进程让 supervisor 自动拉起（比容器重启快，且不影响 Go 主服务）
docker exec chatgpt2api-13 sh -c "supervisorctl status 2>/dev/null || cat /etc/supervisor/conf.d/supervisord.conf 2>/dev/null | grep -E '^\[program' "
