#!/bin/bash
# ============================================
# 异步Google AI代理服务器 - 启动脚本
# 支持优雅启动、停止和进程管理
# ============================================

set -e

# 配置
PORT="${PORT:-8787}"
WORKERS="${WORKERS:-2}"
PID_FILE="${PID_FILE:-/tmp/openai_proxy.pid}"
LOG_FILE="${LOG_FILE:-logs/async_server.log}"
PYTHON="${PYTHON:-python3}"
MODULE="${MODULE:-async_server.py}"

# 颜色输出
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0;m'

# 日志函数
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

# 检查端口是否被占用
check_port() {
    if lsof -i :${PORT} > /dev/null 2>&1; then
        return 0  # 端口被占用
    else
        return 1  # 端口空闲
    fi
}

# 检查进程是否在运行
check_running() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            return 0  # 进程在运行
        else
            # PID文件存在但进程已死，清理
            rm -f "$PID_FILE"
            return 1
        fi
    fi
    return 1
}

# 获取运行状态
get_status() {
    if check_running; then
        PID=$(cat "$PID_FILE")
        echo -e "${GREEN}服务正在运行${NC}"
        echo "PID: $PID"
        echo "端口: $PORT"
        echo "日志: $LOG_FILE"
        if [ -f "$LOG_FILE" ]; then
            echo "最后日志: $(tail -n 1 "$LOG_FILE" 2>/dev/null || echo "无")"
        fi
        return 0
    else
        echo -e "${RED}服务未运行${NC}"
        return 1
    fi
}

# 启动服务
start() {
    log_info "正在启动异步Google AI代理服务器..."

    # 检查是否已在运行
    if check_running; then
        PID=$(cat "$PID_FILE")
        log_warn "服务已运行在 PID $PID"
        log_warn "请先停止旧服务: $0 stop"
        exit 1
    fi

    # 检查端口
    if check_port; then
        log_error "端口 $PORT 已被占用"
        log_error "请检查是否有其他程序占用该端口"
        lsof -i :${PORT} || true
        exit 1
    fi

    # 检查Python文件是否存在
    if [ ! -f "$MODULE" ]; then
        log_error "找不到模块文件: $MODULE"
        log_warn "确保你在项目根目录运行此脚本"
        exit 1
    fi

    # 创建工作目录
    mkdir -p "$(dirname "$LOG_FILE")"
    mkdir -p "$(dirname "$PID_FILE")"

    # 检查Python依赖
    log_info "检查Python依赖..."
    $PYTHON -c "import aiohttp" 2>/dev/null || {
        log_warn "缺少aiohttp依赖，正在安装..."
        pip install aiohttp
    }

    # 检查必要的环境变量
    if [ -z "$GOOGLE_API_KEY" ]; then
        log_warn "未设置 GOOGLE_API_KEY 环境变量"
        read -p "请输入 Google API Key (或留空使用默认值): " user_key
        if [ -n "$user_key" ]; then
            export GOOGLE_API_KEY="$user_key"
        fi
    fi

    # 启动服务
    log_info "使用 $WORKERS 个工作进程启动..."
    log_info "日志输出到: $LOG_FILE"

    # 设置环境变量
    export PYTHONPATH="${PYTHONPATH}:$(pwd)"

    # 后台启动
    nohup $PYTHON -u "$MODULE" > "$LOG_FILE" 2>&1 &
    PID=$!

    # 保存PID
    echo $PID > "$PID_FILE"

    # 等待服务启动
    log_info "等待服务启动..."
    sleep 2

    # 检查是否成功
    if ps -p $PID > /dev/null 2>&1 && check_port; then
        log_success "服务启动成功!"
        log_info "PID: $PID"
        log_info "端口: $PORT"
        log_info "日志: $LOG_FILE"
        log_info "访问: http://localhost:${PORT}/health"

        # 显示前几行日志
        echo ""
        log_info "启动日志:"
        head -n 20 "$LOG_FILE" 2>/dev/null | grep -E "(INFO|ERROR|启动|Starting)" || true

        return 0
    else
        log_error "服务启动失败"
        log_error "检查日志: $LOG_FILE"
        rm -f "$PID_FILE"
        tail -n 50 "$LOG_FILE" || cat "$LOG_FILE" 2>/dev/null || true
        return 1
    fi
}

# 停止服务
stop() {
    log_info "正在停止服务..."

    if ! check_running; then
        log_warn "服务未运行"
        rm -f "$PID_FILE"
        # 确保端口释放
        if check_port; then
            log_warn "清理端口占用..."
            lsof -ti:${PORT} 2>/dev/null | xargs kill -9 2>/dev/null || true
        fi
        return 0
    fi

    PID=$(cat "$PID_FILE")
    log_info "发送SIGTERM到 PID $PID..."

    # 尝试优雅终止
    kill -TERM "$PID" 2>/dev/null

    # 等待进程退出
    for i in {1..30}; do
        if ! ps -p "$PID" > /dev/null 2>&1; then
            log_success "服务已停止"
            rm -f "$PID_FILE"
            return 0
        fi
        if [ $i -le 5 ]; then
            echo -n "."
        fi
        sleep 1
    done

    echo ""
    log_warn "优雅停止失败，强制终止..."
    kill -KILL "$PID" 2>/dev/null || true
    rm -f "$PID_FILE"

    # 确保端口释放
    if check_port; then
        lsof -ti:${PORT} 2>/dev/null | xargs kill -9 2>/dev/null || true
    fi

    log_success "服务已强制停止"
}

# 重启服务
restart() {
    log_info "重启服务..."
    stop
    sleep 2
    start
}

# 查看日志
logs() {
    if [ -f "$LOG_FILE" ]; then
        log_info "实时日志（按Ctrl+C退出）:"
        tail -f "$LOG_FILE"
    else
        log_error "日志文件不存在: $LOG_FILE"
    fi
}

# 健康检查
health() {
    local url="http://localhost:${PORT}/health"
    log_info "检查服务健康状态..."

    if check_running; then
        if command -v curl >/dev/null 2>&1; then
            curl -s "$url" | python3 -m json.tool 2>/dev/null || curl -s "$url"
        else
            log_warn "未安装curl，无法检查API响应"
            get_status
        fi
    else
        log_error "服务未运行"
        exit 1
    fi
}

# 显示用法
usage() {
    cat << EOF
异步Google AI代理服务器 - 进程管理脚本

用法: $0 {start|stop|restart|status|logs|health}

命令:
  start   启动服务
  stop    停止服务
  restart 重启服务
  status  查看状态
  logs    查看实时日志
  health  健康检查

环境变量:
  PORT         服务端口 (默认: 8787)
  WORKERS      工作进程数 (默认: 2)
  PID_FILE     PID文件路径 (默认: /tmp/openai_proxy.pid)
  LOG_FILE     日志文件路径 (默认: logs/async_server.log)
  PYTHON       Python解释器路径 (默认: python3)

示例:
  ./start_async.sh start                  # 启动服务
  PORT=8888 ./start_async.sh start       # 使用自定义端口
  ./start_async.sh status                # 查看状态
  ./start_async.sh health                # 健康检查

EOF
}

# 处理命令
case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    status)
        get_status
        ;;
    logs)
        logs
        ;;
    health)
        health
        ;;
    *)
        usage
        exit 1
        ;;
esac
