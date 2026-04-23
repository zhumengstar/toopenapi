#!/bin/bash
# Google AI → OpenAI Protocol Proxy Server
# 重启服务脚本

cd "$(dirname "$0")"

echo "Restarting server..."

# 停止服务
./stop.sh

# 等待一下
sleep 1

# 启动服务
./start.sh
