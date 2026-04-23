#!/bin/bash
# Google AI → OpenAI Protocol Proxy Server
# 后台运行启动脚本

cd "$(dirname "$0")"

# 检查是否已运行
if lsof -i :8787 > /dev/null 2>&1; then
    echo "❌ Port 8787 is already in use"
    echo "   Run './stop.sh' to stop the existing server first"
    exit 1
fi

# 创建日志目录
mkdir -p logs

# 后台启动服务
echo "🚀 Starting server..."
nohup python3 server.py > logs/server.log 2>&1 &

# 等待服务启动
sleep 2

# 检查是否启动成功
if lsof -i :8787 > /dev/null 2>&1; then
    echo "✅ Server started successfully!"
    echo "   Server running at: http://localhost:8787"
    echo "   Logs: logs/server.log"
else
    echo "❌ Failed to start server"
    echo "   Check logs/server.log for details"
    cat logs/server.log
    exit 1
fi
