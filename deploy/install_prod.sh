Toopenapi/deploy/install_prod.sh
```

```bash
#!/bin/bash
# ==============================================================================
# Google AI OpenAI Proxy - Production Installation Script
# Automated production-ready deployment for Ubuntu/Debian systems
# ==============================================================================

set -euo pipefail

# Color output
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m'

# Configuration
readonly SERVICE_NAME="openai-proxy"
readonly SERVICE_USER="openai-proxy"
readonly INSTALL_DIR="/opt/${SERVICE_NAME}"
readonly LOG_DIR="/var/log/${SERVICE_NAME}"
readonly PID_DIR="/run/${SERVICE_NAME}"
readonly CONFIG_DIR="/etc/${SERVICE_NAME}"
readonly SYSTEMD_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

# Script paths
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly PROJECT_ROOT="$(dirname "${SCRIPT_DIR}")"

# Logging
log() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $*"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $*"
}

error() {
    echo -e "${RED}[ERROR]${NC} $*" >&2
    exit 1
}

# Preflight checks
preflight_checks() {
    log "运行环境预检..."

    # Check root privileges
    if [[ $EUID -ne 0 ]]; then
        error "此脚本需要 root 权限运行。请使用 sudo。"
    fi

    # Check OS compatibility
    if ! command -v apt-get &> /dev/null; then
        error "此脚本仅支持 Ubuntu/Debian 系统"
    fi

    # Check Python version
    if command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
        log "检测到 Python $PYTHON_VERSION"
        if (( $(echo "$PYTHON_VERSION < 3.10" | bc -l) )); then
            error "Python 3.10+ 是必需的"
        fi
    else
        error "未找到 Python3。请先安装 Python 3.10 或更高版本"
    fi

    # Check disk space (at least 500MB)
    AVAILABLE_SPACE=$(df -m /opt | tail -1 | awk '{print $4}')
    if [[ $AVAILABLE_SPACE -lt 500 ]]; then
        warn "可用磁盘空间少于 500MB，可能安装失败"
    fi

    # Check for required tools
    for tool in curl gcc systemd; do
        if ! command -v "$tool" &> /dev/null; then
            warn "工具 '$tool' 未找到，将尝试安装"
        fi
    done

    log "预检完成"
}

# Install dependencies
install_dependencies() {
    log "安装系统依赖..."

    apt-get update
    apt-get install -y \
        python3 \
        python3-pip \
        python3-venv \
        gcc \
        curl \
        systemd \
        git \
        build-essential

    log "系统依赖安装完成"
}

# Create service user
create_service_user() {
    log "创建服务用户..."

    if ! id -u "${SERVICE_USER}" &>/dev/null; then
        useradd --system \
                --user-group \
                --home-dir "${INSTALL_DIR}" \
                --no-create-home \
                --comment "OpenAI Proxy Service" \
                "${SERVICE_USER}"
        log "创建服务用户: ${SERVICE_USER}"
    else
        log "服务用户已存在: ${SERVICE_USER}"
    fi
}

# Setup directories
setup_directories() {
    log "配置目录结构..."

    # Create directories with proper permissions
    mkdir -p "${INSTALL_DIR}"
    mkdir -p "${LOG_DIR}"
    mkdir -p "${PID_DIR}"
    mkdir -p "${CONFIG_DIR}"

    # Set ownership and permissions
    chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}"
    chown -R "${SERVICE_USER}:${SERVICE_USER}" "${LOG_DIR}"
    chown -R "${SERVICE_USER}:${SERVICE_USER}" "${PID_DIR}"
    chown -R "${SERVICE_USER}:${SERVICE_USER}" "${CONFIG_DIR}"

    chmod 755 "${INSTALL_DIR}"
    chmod 755 "${LOG_DIR}"
    chmod 755 "${PID_DIR}"
    chmod 755 "${CONFIG_DIR}"

    log "目录结构配置完成"
}

# Install Python dependencies
install_python_deps() {
    log "安装 Python 依赖..."

    cd "${INSTALL_DIR}"

    # Create virtual environment
    sudo -u "${SERVICE_USER}" python3 -m venv venv

    # Activate virtual env and install dependencies
    sudo -u "${SERVICE_USER}" bash -c "
        source venv/bin/activate
        pip install --upgrade pip setuptools wheel
        pip install -r requirements_async.txt
    "

    log "Python 依赖安装完成"
}

# Copy project files
copy_files() {
    log "复制项目文件..."

    # Copy all necessary files
    cp -r "${PROJECT_ROOT}/async_server.py" "${INSTALL_DIR}/"
    cp -r "${PROJECT_ROOT}/requirements_async.txt" "${INSTALL_DIR}/"
    cp -r "${SCRIPT_DIR}/" "${INSTALL_DIR}/deploy"

    # Create empty logs file
    touch "${LOG_DIR}/async_server.log"
    chown "${SERVICE_USER}:${SERVICE_USER}" "${LOG_DIR}/async_server.log"

    # Set permissions
    chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}"

    log "项目文件复制完成"
}

# Create environment configuration file
create_env_file() {
    log "创建环境配置文件..."

    cat > "${CONFIG_DIR}/env" << EOF
# OpenAI Proxy Service - Environment Variables
# Generated on: $(date)

# Required: Google AI API Key
# Set this to your actual API key before starting the service
GOOGLE_API_KEY=${GOOGLE_API_KEY:-}

# Service Configuration
PORT=${PORT:-8787}
DEFAULT_MODEL=${DEFAULT_MODEL:-gemma-4-31b-it}
CACHE_DURATION=${CACHE_DURATION:-300}
REQUEST_TIMEOUT=${REQUEST_TIMEOUT:-120}
LOG_LEVEL=${LOG_LEVEL:-INFO}
LOG_FILE=${LOG_DIR}/async_server.log
PID_FILE=${PID_DIR}/openai_proxy_async.pid
CORS_ORIGINS=${CORS_ORIGINS:-*}
MAX_RETRIES=${MAX_RETRIES:-3}
SKIP_SSL_VERIFY=${SKIP_SSL_VERIFY:-true}
EOF

    chmod 600 "${CONFIG_DIR}/env"
    chown "${SERVICE_USER}:${SERVICE_USER}" "${CONFIG_DIR}/env"

    log "环境配置文件 created at: ${CONFIG_DIR}/env"
    log "请编辑此文件并设置你的 GOOGLE_API_KEY"
}

# Install systemd service
install_systemd_service() {
    log "安装 systemd 服务..."

    if [[ -f "${SCRIPT_DIR}/openai-proxy.service" ]]; then
        cp "${SCRIPT_DIR}/openai-proxy.service" "${SYSTEMD_PATH}"

        # Replace placeholder variables
        sed -i "s|%GOOGLE_API_KEY%|${GOOGLE_API_KEY}|g" "${SYSTEMD_PATH}"
        sed -i "s|%PORT%|${PORT:-8787}|g" "${SYSTEMD_PATH}"

        # Reload systemd
        systemctl daemon-reload

        log "systemd 服务已安装: ${SYSTEMD_PATH}"
    else
        error "未找到 systemd 服务文件: ${SCRIPT_DIR}/openai-proxy.service"
    fi
}

# Security hardening
security_hardening() {
    log "应用安全加固..."

    # Set restrictive permissions on service files
    chmod 644 "${SYSTEMD_PATH}"

    # Create firewall rules (if ufw is available)
    if command -v ufw &> /dev/null; then
        ufw allow "${PORT:-8787}/tcp" comment "OpenAI Proxy Service"
        log "防火墙规则已添加"
    else
        warn "ufw 未安装，跳过防火墙配置"
    fi

    # Set system limits
    cat > "/etc/security/limits.d/${SERVICE_NAME}.conf" << EOF
${SERVICE_USER} soft nofile 65536
${SERVICE_USER} hard nofile 65536
${SERVICE_USER} soft nproc 4096
${SERVICE_USER} hard nproc 4096
EOF

    log "安全加固完成"
}

# Enable and start service
start_service() {
    log "启用并启动服务..."

    systemctl enable "${SERVICE_NAME}"
    systemctl start "${SERVICE_NAME}"

    # Wait for service to start
    sleep 5

    # Check service status
    if systemctl is-active --quiet "${SERVICE_NAME}"; then
        log "✓ 服务已成功启动"
        systemctl status "${SERVICE_NAME}" --no-pager --lines=20
    else
        error "服务启动失败，请检查日志: journalctl -u ${SERVICE_NAME} -n 50"
    fi
}

# Create management scripts
create_management_scripts() {
    log "创建管理脚本..."

    # Create simple helper script
    cat > "/usr/local/bin/${SERVICE_NAME}-ctl" << 'EOF'
#!/bin/bash
SERVICE_NAME="openai-proxy"
case "$1" in
    status)
        systemctl status $SERVICE_NAME
        ;;
    start)
        systemctl start $SERVICE_NAME
        ;;
    stop)
        systemctl stop $SERVICE_NAME
        ;;
    restart)
        systemctl restart $SERVICE_NAME
        ;;
    logs)
        journalctl -u $SERVICE_NAME -f
        ;;
    *)
        echo "Usage: $0 {status|start|stop|restart|logs}"
        exit 1
        ;;
esac
EOF

    chmod +x "/usr/local/bin/${SERVICE_NAME}-ctl"

    log "管理脚本 created: ${SERVICE_NAME}-ctl"
}

# Create uninstall script
create_uninstall_script() {
    log "创建卸载脚本..."

    cat > "${INSTALL_DIR}/uninstall.sh" << 'EOF'
#!/bin/bash
# OpenAI Proxy Service - Uninstall Script

set -euo pipefail

SERVICE_NAME="openai-proxy"
INSTALL_DIR="/opt/openai-proxy"

# Check root
if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root"
    exit 1
fi

echo "Uninstalling OpenAI Proxy Service..."

# Stop and disable service
systemctl stop $SERVICE_NAME 2>/dev/null || true
systemctl disable $SERVICE_NAME 2>/dev/null || true

# Remove systemd service
rm -f /etc/systemd/system/$SERVICE_NAME.service
systemctl daemon-reload

# Remove files
rm -rf $INSTALL_DIR
rm -rf /var/log/$SERVICE_NAME
rm -rf /etc/$SERVICE_NAME
rm -f /usr/local/bin/$SERVICE_NAME-ctl

# Remove user (optional)
read -p "Remove service user '$SERVICE_NAME'? [y/N]: " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    userdel $SERVICE_NAME 2>/dev/null || true
fi

echo "Uninstall complete!"
EOF

    chmod +x "${INSTALL_DIR}/uninstall.sh"
    chown "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}/uninstall.sh"

    log "卸载脚本 created: ${INSTALL_DIR}/uninstall.sh"
}

# Display installation summary
show_summary() {
    log "\n=============================="
    log "安装完成！"
    log "==============================\n"

    echo "服务信息:"
    echo "  - 服务名称: ${SERVICE_NAME}"
    echo "  - 安装目录: ${INSTALL_DIR}"
    echo "  - 日志目录: ${LOG_DIR}"
    echo "  - 配置文件: ${CONFIG_DIR}/env"
    echo "  - Systemd 服务: ${SYSTEMD_PATH}"
    echo "  - 管理工具: ${SERVICE_NAME}-ctl"
    echo ""

    echo "下一步操作:"
    echo "  1. 编辑配置文件: nano ${CONFIG_DIR}/env"
    echo "  2. 设置 GOOGLE_API_KEY"
    echo "  3. 重启服务: systemctl restart ${SERVICE_NAME}"
    echo "  4. 查看日志: journalctl -u ${SERVICE_NAME} -f"
    echo "  5. 验证服务: curl http://localhost:${PORT:-8787}/health"
    echo ""

    echo "常用命令:"
    echo "  - 启动: systemctl start ${SERVICE_NAME}"
    echo "  - 停止: systemctl stop ${SERVICE_NAME}"
    echo "  - 重启: systemctl restart ${SERVICE_NAME}"
    echo "  - 状态: ${SERVICE_NAME}-ctl status"
    echo "  - 日志: ${SERVICE_NAME}-ctl logs"
    echo "  - 卸载: ${INSTALL_DIR}/uninstall.sh"
    echo ""

    warn "重要: 请确保在启动服务前配置 GOOGLE_API_KEY！"
}

# Rollback on failure
rollback() {
    error "安装过程中出现错误，正在回滚..."

    # Stop service if it was started
    systemctl stop "${SERVICE_NAME}" 2>/dev/null || true
    systemctl disable "${SERVICE_NAME}" 2>/dev/null || true

    # Remove files
    rm -f "${SYSTEMD_PATH}"
    rm -rf "${INSTALL_DIR}"
    rm -rf "${LOG_DIR}"
    rm -rf "${PID_DIR}"
    rm -rf "${CONFIG_DIR}"

    # Remove user (if created)
    if id -u "${SERVICE_USER}" &>/dev/null; then
        read -p "是否删除服务用户 '${SERVICE_USER}'? [y/N]: " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            userdel "${SERVICE_USER}" 2>/dev/null || true
        fi
    fi

    systemctl daemon-reload

    log "回滚完成"
    exit 1
}

# Main installer
main() {
    # Set up error handling
    trap rollback ERR

    log "====================================================="
    log "OpenAI Proxy 生产环境安装"
    log "====================================================="

    # Show pre-installation warning
    warn "此脚本将安装 OpenAI Proxy 服务到生产环境"
    warn "请确保您已备份重要数据"
    echo ""

    read -p "继续安装? [y/N]: " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log "安装已取消"
        exit 0
    fi

    # Run installation steps
    preflight_checks
    install_dependencies
    create_service_user
    setup_directories
    copy_files
    create_env_file
    install_python_deps
    install_systemd_service
    security_hardening
    create_management_scripts
    create_uninstall_script
    start_service
    show_summary

    log "安装过程完成！"
}

# Run installer
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
