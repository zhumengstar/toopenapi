3. 接下来需要包含 `<file_path>` 和 `<edit_description>` 的注释
4. 然后才是文件的实际内容
5. 以三个反引号结束

由于工具调用已被禁用，我需要直接输出文件内容，而不是使用工具调用。 </think> ```
<file_path> Toopenapi/docker-start.sh </file_path>
<edit_description> 一键 Docker 部署脚本，提供交互式配置、自动检测和测试功能 </edit_description>
#!/bin/bash
# Google AI Proxy - Docker 快速部署脚本 - v1.0.0
# 一键部署脚本，自动检查环境、配置服务并验证部署

set -e

# ==================== 颜色配置 ====================
green='\\033[0;32m'
yellow='\\033[1;33m'
red='\\033[0;31m'
blue='\\033[0;34m'
cyan='\\033[0;36m'
nc='\\033[0m'

# ==================== 日志函数 ====================
info() {
echo -e "${blue}[INFO]${nc} $1"
}

success() {
echo -e "${green}[SUCCESS]${nc} $1"
}

warn() {
echo -e "${yellow}[WARN]${nc} $1"
}

error() {
echo -e "${red}[ERROR]${nc} $1"
}

header() {
echo -e "\\n${cyan}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${nc}"
echo -e "${cyan}  $1${nc}"
echo -e "${cyan}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${nc}\\n"
}

# ==================== 检查要求 ====================
check_requirements() {
header "环境检查"

# 检查 Docker
if ! command -v docker &> /dev/null; then
error "Docker 未安装，请先安装 Docker"
exit 1
fi

# 检查 Docker Compose
if ! command -v docker-compose &> /dev/null; then
error "Docker Compose 未安装，请先安装 Docker Compose"
exit 1
fi

# 检查 Docker 服务状态
if ! docker info &> /dev/null; then
error "Docker 服务未运行，请启动 Docker 服务"
exit 1
fi

success "✓ Docker 环境检查通过"
info "Docker 版本: $(docker --version)"
info "Docker Compose 版本: $(docker-compose --version)"
}

# ==================== 检查配置文件 ====================
check_env_file() {
header "配置文件检查"

if [ ! -f ".env" ]; then
warn "⚠ 未找到 .env 文件"

if [ -f ".env.example" ]; then
info "从 .env.example 创建 .env 文件"
cp .env.example .env
warn "⚠ 请配置 Google API Key"

# 自动打开编辑器
if command -v nano &> /dev/null; then
nano .env
elif command -v vim &> /dev/null; then
vim .env
else
info "请手动编辑 .env 文件，设置 GOOGLE_API_KEY"
fi
else
error "未发现 .env.example 模板文件"
exit 1
fi
fi

# 验证 GOOGLE_API_KEY
if grep -q "GOOGLE_API_KEY=your_google_ai_api_key_here" .env; then
error "GOOGLE_API_KEY 未配置，请在 .env 文件中设置"
exit 1
fi

if grep -E "^GOOGLE_API_KEY=\\s*$" .env; then
error "GOOGLE_API_KEY 为空，请在 .env 文件中设置"
exit 1
fi

success "✓ 配置文件检查通过"
}

# ==================== 检查端口可用性 ====================
check_port_availability() {
header "端口检查"

# 从 .env 文件中读取端口
if [ -f ".env" ]; then
source .env 2>/dev/null || true
PORT=${PORT:-8787}
else
PORT=8787
fi

info "检查端口 $PORT 是否可用..."

if lsof -i ":$PORT" &> /dev/null; then
warn "端口 $PORT 已被占用"
read -r -p "是否使用其他端口？(输入新端口或回车使用 $PORT): " new_port

if [ -n "$new_port" ]; then
PORT=$new_port
sed -i "s/^PORT=.*/PORT=$PORT/" .env
success "端口已更改为: $PORT"
else
warn "继续使用端口 $PORT (可能导致冲突)"
fi
else
success "✓ 端口 $PORT 可用"
fi
}

# ==================== 启动服务 ====================
start_service() {
header "服务启动"

info "正在拉取基础镜像..."
docker-compose pull --quiet

info "正在构建 Docker 镜像..."
if docker-compose build --no-cache; then
success "✓ 镜像构建成功"
else
error "镜像构建失败"
exit 1
fi

info "正在启动 Docker 容器..."
if docker-compose up -d; then
success "✓ 容器启动成功"
else
error "容器启动失败"
exit 1
fi

# 等待服务初始化
sleep 5
}

# ==================== 健康检查 ====================
wait_for_healthy() {
header "服务健康检查"

max_attempts=30
attempt=0

info "等待服务就绪 (最多 ${max_attempts} 秒)..."

while [ $attempt -lt $max_attempts ]; do
if curl -s http://localhost:${PORT}/health &> /dev/null; then
success "✓ 服务已就绪"
return 0
fi

attempt=$((attempt + 1))
echo -n "."
sleep 1
done

error "\n服务启动超时"
return 1
}

# ==================== 验证服务 ====================
validate_service() {
header "服务验证"

# 容器状态检查
if docker-compose ps | grep -q "Up"; then
success "✓ 容器运行正常"
else
error "容器未运行"
docker-compose ps
exit 1
fi

# 健康检查
health_response=$(curl -s http://localhost:${PORT}/health 2>/dev/null)
if [ -n "$health_response" ]; then
success "✓ 健康检查通过"
echo "响应: $health_response" | python3 -m json.tool 2>/dev/null || echo "$health_response"
else
error "健康检查失败"
exit 1
fi

# 模型列表检查
models_response=$(curl -s http://localhost:${PORT}/v1/models 2>/dev/null)
if [ -n "$models_response" ]; then
success "✓ 模型列表获取成功"
model_count=$(echo "$models_response" | grep -o '"id"' | wc -l)
info "可用模型数量: $model_count"
else
warn "⚠ 模型列表获取失败（可能是 API Key 问题）"
fi
}

# ==================== 显示服务信息 ====================
show_service_info() {
header "部署完成"

success "✅ Google AI Proxy 部署成功！"
echo
info "服务地址"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "服务地址: ${cyan}http://localhost:${PORT}${nc}"
echo -e "应用地址: ${cyan}http://localhost:${PORT}/v1/chat/completions${nc}"
echo -e "模型列表: ${cyan}http://localhost:${PORT}/v1/models${nc}"
echo -e "健康检查: ${cyan}http://localhost:${PORT}/health${nc}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo
info "管理命令"
echo "查看日志: ${yellow}docker-compose logs -f${nc}"
echo "停止服务: ${yellow}docker-compose down${nc}"
echo "重启服务: ${yellow}docker-compose restart${nc}"
echo "查看状态: ${yellow}docker-compose ps${nc}"
echo "进入容器: ${yellow}docker-compose exec google-ai-openai-proxy /bin/bash${nc}"
echo
info "配置文件"
echo "环境变量: ${yellow}.env${nc}"
echo "详细文档: ${yellow}DOCKER_DEPLOY.md${nc}"
}

# ==================== 测试 API ====================
test_api() {
header "API 测试"

warn "⚠ 注意: 此测试将消耗 Google API 额度"

read -r -p "是否要测试对话接口？ (y/N): " response
if [[ "$response" =~ ^[Yy]$ ]]; then
info "正在测试对话接口..."

test_result=$(curl -s http://localhost:${PORT}/v1/chat/completions \
-H "Content-Type: application/json" \
-d '{"model": "gemma-4-31b-it", "messages": [{"role": "user", "content": "Hello! 请用中文回复"}], "stream": false}' 2>&1)

if echo "$test_result" | grep -q '"message"'; then
success "✓ API 测试通过"
echo "$test_result" | python3 -m json.tool 2>/dev/null || echo "$test_result"
else
error "API 测试失败"
echo "错误详情: $test_result"
fi
else
info "跳过 API 测试"
fi
}

# ==================== 显示日志 ====================
show_logs() {
read -r -p "是否查看实时日志？ (y/N): " response
if [[ "$response" =~ ^[Yy]$ ]]; then
info "正在显示日志... (按 Ctrl+C 退出)"
docker-compose logs -f --tail=50
fi
}

# ==================== 主函数 ====================
main() {
clear
echo -e "${cyan}"
echo "╔════════════════════════════════════════════════════╗"
echo "║ Google AI to OpenAI Protocol Proxy                 ║"
echo "║ Docker 一键部署脚本                                ║"
echo "╚════════════════════════════════════════════════════╝"
echo -e "${nc}"

check_requirements
check_env_file
check_port_availability
start_service

if wait_for_healthy; then
validate_service
show_service_info
test_api
show_logs
else
error "部署失败，请查看日志"
docker-compose logs --tail=100
exit 1
fi

echo
success "✅ 部署完成！"
header "后续步骤"
echo "1. 配置您的应用使用此代理服务"
echo "2. 生产环境建议配置 Nginx 反向代理和 SSL"
echo "3. 查看 DOCKER_DEPLOY.md 获取更多高级配置"
echo
}

# ==================== Help 函数 ====================
show_help() {
echo "Google AI Proxy Docker 一键部署脚本"
echo
echo "使用方法: $0 [选项]"
echo
echo "选项:"
echo " -h, --help   显示帮助信息"
echo " -c, --check  仅检查环境"
echo " -s, --skip   跳过 API 测试"
echo
echo "示例:"
echo " $0              # 完整部署"
echo " $0 --check      # 仅检查环境"
echo " $0 --skip       # 部署但跳过 API 测试"
}

# ==================== 脚本入口 ====================
# 处理命令行参数
case "$1" in
-h|--help)
show_help
exit 0
;;
-c|--check)
check_requirements
check_env_file
exit 0
;;
-s|--skip)
export SKIP_API_TEST=1
main
;;
"")
main
;;
*)
error "未知参数: $1"
show_help
exit 1
;;
esac
