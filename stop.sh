#!/bin/bash
# Google AI → OpenAI Protocol Proxy Server
# 停止服务脚本

echo "Stopping server..."

# 查找并终止进程
pkill -f "python3 server.py" 2>/dev/null

# 等待一下让进程完全退出
sleep 1

# 检查是否还有进程在运行
if lsof -i :8787 > /dev/null 2>&1; then
    echo "❌ Server is still running, forcing kill..."
    pkill -9 -f "python3 server.py" 2>/dev/null
    sleep 1
fi

# 再次检查
if lsof -i :8787 > /dev/null 2>&1; then
    echo "❌ Failed to stop server"
    exit 1
else
    echo "✅ Server stopped successfully"
fi
