#!/bin/sh
set -e

# 首次运行：确保数据卷目录存在，并在缺失时生成最小 config.json，
# 避免用户必须手工准备挂载内容（本地/线上一致体验）。
mkdir -p /data
if [ ! -f /data/config.json ]; then
  cat > /data/config.json <<EOF
{
  "auth-key": "${CHATGPT2API_AUTH_KEY:-}",
  "proxy": "",
  "data_dir": "/data"
}
EOF
  echo "[entrypoint] 已生成默认 /data/config.json（auth-key 取自 CHATGPT2API_AUTH_KEY）"
fi

# regiforge 数据目录（如用户挂了卷则沿用，否则容器内自持）
mkdir -p /opt/regiforge/data

echo "[entrypoint] 启动 supervisord（chatgpt2api :3077 + regiforge 127.0.0.1:8787）"
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
