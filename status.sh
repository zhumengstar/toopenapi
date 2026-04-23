#!/bin/bash
# Google AI → OpenAI Protocol Proxy Server
# 状态检查脚本

cd "$(dirname "$0")"

echo "╭─────────────────────────────────────╮"
echo "│     Server Status Check             │"
echo "╰─────────────────────────────────────╯"
echo ""

# 检查端口是否被占用
if lsof -i :8787 > /dev/null 2>&1; then
    echo "🟢 Server is RUNNING"
    echo ""
    echo "┌─ Process Info ─────────────────────┐"
    lsof -i :8787 | tail -n +2 | while read line; do
        echo "│ $line" | head -c 38
        echo " │"
    done
    echo "└────────────────────────────────────┘"
    echo ""
    
    # 测试 API
    echo "┌─ API Test ─────────────────────────┐"
    
    # 健康检查
    health=$(curl -s http://localhost:8787/health 2>/dev/null)
    if [ $? -eq 0 ]; then
        echo "│ ✅ Health: OK                       │"
    else
        echo "│ ❌ Health: FAILED                  │"
    fi
    
    # 模型列表
    models=$(curl -s http://localhost:8787/v1/models 2>/dev/null)
    if [ $? -eq 0 ]; then
        count=$(echo "$models" | grep -o '"id"' | wc -l)
        echo "│ ✅ Models API: OK ($count models)   │"
    else
        echo "│ ❌ Models API: FAILED              │"
    fi
    
    echo "└────────────────────────────────────┘"
    
else
    echo "🔴 Server is STOPPED"
    echo ""
    echo "Run './start.sh' to start the server"
fi

echo ""
echo "┌─ Logs ─────────────────────────────┐"
if [ -f "logs/server.log" ]; then
    tail -5 logs/server.log | while read line; do
        echo "│ ${line:0:36}" | head -c 36
        echo " │"
    done
else
    echo "│ No log file found                 │"
fi
echo "└────────────────────────────────────┘"
