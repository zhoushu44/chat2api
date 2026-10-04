#!/bin/sh
# 干跑验证：只测试配置抓取逻辑，不重建容器
NAME=chatgpt2api-13

echo "=== 1. 端口解析 ==="
PORTS=$(docker inspect "$NAME" --format '{{range $p, $conf := .HostConfig.PortBindings}}{{$p}}={{range $conf}}{{.HostPort}}{{end}} {{end}}')
echo "raw: $PORTS"
for p in $PORTS; do
  host=${p%%=*}; port=${p##*=}
  echo "  -> -p ${port}:${host%/*}"
done

echo
echo "=== 2. 挂载解析 ==="
MOUNTS=$(docker inspect "$NAME" --format '{{range .Mounts}}{{if eq .Type "bind"}}-v {{.Source}}:{{.Destination}} {{end}}{{end}}')
echo "raw: $MOUNTS"

echo
echo "=== 3. 环境变量解析 ==="
ENVS=$(docker inspect "$NAME" --format '{{range .Config.Env}}{{println .}}{{end}}' \
  | grep -vE '^(PATH|LANG|GPG_KEY|PYTHON_|DISPLAY|OPENAI_SENTINEL_NODE_PATH)=' \
  | grep -v '^$' \
  | sed 's/^/-e /' | tr '\n' ' ')
echo "raw: $ENVS"
echo "条目数: $(echo $ENVS | wc -w)"

echo
echo "=== 4. shm 转换 ==="
SHM=$(docker inspect "$NAME" --format '{{.HostConfig.ShmSize}}')
echo "raw bytes: $SHM -> $(echo $SHM | awk '{print $1/1024/1024"m"}')"

echo
echo "=== 5. restart 策略 ==="
docker inspect "$NAME" --format '{{.HostConfig.RestartPolicy.Name}}'

echo
echo "=== 6. 拼装出的完整 docker run（预览，不执行）==="
RESTART=$(docker inspect "$NAME" --format '{{.HostConfig.RestartPolicy.Name}}')
echo "docker run -d \\"
echo "  --name $NAME \\"
echo "  --restart $RESTART \\"
echo "  --init \\"
echo "  --shm-size $(echo $SHM | awk '{print $1/1024/1024"m"}') \\"
echo "  $MOUNTS \\"
echo "  $ENVS \\"
for p in $PORTS; do host=${p%%=*}; port=${p##*=}; echo "  -p ${port}:${host%/*} \\"; done
echo "  zhoushu1/chat2api:18.0"
