#!/bin/bash
# ============================================================
# OpenAI Proxy Service - Automated Test Script
# Test all interfaces: health, models, chat completions (streaming & non-streaming)
# ============================================================

set -e

# ==================== Configuration ====================
PORT=8787
API_KEY="AIzaSyAzEnf92GCrLSbeFpqYtVzN0Y8gnye-j_s"
BASE_URL="http://localhost:${PORT}"
LOG_FILE="logs/test_report.log"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ==================== Helper Functions ====================
log() {
    echo -e "${GREEN}[INFO]${NC} $1" | tee -a "$LOG_FILE"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1" | tee -a "$LOG_FILE"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1" | tee -a "$LOG_FILE"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1" | tee -a "$LOG_FILE"
}

section() {
    echo "" | tee -a "$LOG_FILE"
    echo -e "${BLUE}============================================================${NC}" | tee -a "$LOG_FILE"
    echo -e "${BLUE}$1${NC}" | tee -a "$LOG_FILE"
    echo -e "${BLUE}============================================================${NC}" | tee -a "$LOG_FILE"
    echo "" | tee -a "$LOG_FILE"
}

check_port() {
    if lsof -i :$PORT > /dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

# ==================== Test Functions ====================
test_health() {
    section "Test 1: Health Check Interface"

    log "Sending GET request to ${BASE_URL}/health"
    start_time=$(date +%s)

    response=$(curl -s -w "\n%{http_code}" "${BASE_URL}/health" 2>&1)
    http_code=$(echo "$response" | tail -n 1)
    body=$(echo "$response" | sed '$d')

    end_time=$(date +%s)
    duration=$((end_time - start_time))

    if [ "$http_code" == "200" ]; then
        success "Health check successful"
        log "Response: $body"
        log "Response time: ${duration}s"

        # Check if Google API is reachable using Python
        reachable=$(echo "$body" | python3 -c "import sys, json; data=json.load(sys.stdin); print('yes' if data.get('google_api_reachable') == True else 'no')" 2>/dev/null || echo "no")
        if [ "$reachable" == "yes" ]; then
            success "Google API is reachable"
            return 0
        else
            warn "Google API is not reachable"
            return 1
        fi
    else
        error "Health check failed with HTTP code: $http_code"
        log "Response: $body"
        return 1
    fi
}

test_models() {
    section "Test 2: Model List Interface"

    log "Sending GET request to ${BASE_URL}/v1/models"
    start_time=$(date +%s)

    response=$(curl -s -w "\n%{http_code}" "${BASE_URL}/v1/models" 2>&1)
    http_code=$(echo "$response" | tail -n 1)
    body=$(echo "$response" | sed '$d')

    end_time=$(date +%s)
    duration=$((end_time - start_time))

    if [ "$http_code" == "200" ]; then
        success "Model list retrieved successfully"
        log "Response time: ${duration}s"

        	# Check if models are present
        	model_count=$(echo "$body" | python3 -c "import sys, json; data=json.load(sys.stdin); d=data.get('data', []); print(len(d) if isinstance(d, list) else 0)" 2>/dev/null || echo "0")

        	if [ "$model_count" -gt 0 ]; then
            success "Retrieved $model_count models"
            log "First few models:"
            echo "$body" | python3 -m json.tool 2>/dev/null | head -n 30 | tee -a "$LOG_FILE"
            return 0
        else
            warn "No models found in response"
            return 1
        fi
    else
        error "Model list request failed with HTTP code: $http_code"
        log "Response: $body"
        return 1
    fi
}

test_chat_completions() {
    section "Test 3: Chat Completions (Non-Streaming)"

    log "Sending POST request to ${BASE_URL}/v1/chat/completions (non-streaming)"
    start_time=$(date +%s)

    response=$(curl -s -w "\n%{http_code}" "${BASE_URL}/v1/chat/completions" \
        -H "Content-Type: application/json" \
        -d "{
            \"model\": \"gemma-4-31b-it\",
            \"messages\": [
                {\"role\": \"user\", \"content\": \"Hello! Who are you?\"}
            ],
            \"stream\": false
        }" 2>&1)

    http_code=$(echo "$response" | tail -n 1)
    body=$(echo "$response" | sed '$d')

    end_time=$(date +%s)
    duration=$((end_time - start_time))

    if [ "$http_code" == "200" ]; then
        success "Chat completion successful"
        log "Response time: ${duration}s"

        # Validate OpenAI format
        if echo "$body" | python3 -c "import sys, json; data=json.load(sys.stdin); sys.exit(0 if data.get('object')=='chat.completion' else 1)" 2>/dev/null; then
            success "Response format is correct OpenAI format"
            log "Response preview:"
            echo "$body" | python3 -m json.tool 2>/dev/null | head -n 20 | tee -a "$LOG_FILE"

            # Check for content
            content=$(echo "$body" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data['choices'][0]['message']['content'][:100])" 2>/dev/null || echo "")
            if [ -n "$content" ]; then
                success "Response contains assistant content"
                return 0
            fi
        else
            error "Response format is not valid OpenAI format"
            return 1
        fi
    else
        error "Chat completion failed with HTTP code: $http_code"
        log "Response: $body"
        return 1
    fi
}

test_streaming() {
    section "Test 4: Chat Completions (Streaming/SSE)"

    log "Sending POST request to ${BASE_URL}/v1/chat/completions (streaming)"
    start_time=$(date +%s.%N)

    response_file="/tmp/stream_response_$$.txt"

    start_time=$(date +%s)

    curl -N -w "\n%{http_code}" "${BASE_URL}/v1/chat/completions" \
        -H "Content-Type: application/json" \
        -d "{
            \"model\": \"gemma-4-31b-it\",
            \"messages\": [
                {\"role\": \"user\", \"content\": \"Count to 5\"}
            ],
            \"stream\": true,
            \"max_tokens\": 50
        }" > "$response_file" 2>&1 &

    curl_pid=$!
    sleep 5  # Give it time to stream

    if kill -0 $curl_pid 2>/dev/null; then
        kill $curl_pid 2>/dev/null || true
    fi

    wait $curl_pid 2>/dev/null || true

    response=$(cat "$response_file")
    http_code=$(echo "$response" | tail -n 1)
    body=$(echo "$response" | sed '$d' | head -n 30)

    rm -f "$response_file"

    end_time=$(date +%s)
    duration=$((end_time - start_time))

    	# For streaming, body content is more important than http_code
    	# Remove curl progress output from body
    	body=$(echo "$body" | grep -v "^  " | grep -v "%" | grep -v "Dload")

    	if [ -n "$body" ]; then
        success "Streaming response received"
        log "Stream duration: ${duration}s"

        # Check if it contains SSE format
        if echo "$body" | grep -q "^data: "; then
            success "SSE format is correct"

            	# Count chunks (remove curl progress first)
            	clean_body=$(echo "$body" | grep -v "^  " | grep -v "%" | grep -v "Dload" | grep -v "Total")
            	chunk_count=$(echo "$clean_body" | grep -c "^data: " || echo "0")
            log "Number of chunks: $chunk_count"

            # Check for stream completion
            	if echo "$clean_body" | grep -q "data: \[DONE\]"; then
                success "Stream completed with [DONE] marker"

                # Show first few chunks
                log "First few chunks:"
                	echo "$clean_body" | grep "^data:" | head -n 3 | tee -a "$LOG_FILE"
                return 0
            else
                warn "Stream did not contain [DONE] marker"
                return 1
            fi
        else
            warn "Response does not seem to be in SSE format"
            return 1
        fi
    else
        error "Streaming request failed with HTTP code: $http_code"
        log "Response: $body"
        return 1
    fi
}

# ==================== Main Script ====================

main() {
    cd "$PROJECT_DIR"

    section "OpenAI Proxy Service - Automated Test Suite"
    log "Starting tests at $(date)"
    log "Project directory: $PROJECT_DIR"
    log "API Key: ${API_KEY:0:15}..."

    # Create logs directory
    mkdir -p logs

    # Clear previous log
    > "$LOG_FILE"
    log "Test log will be written to: $LOG_FILE"

    # Stop any existing service
    section "Step 1: Stop Existing Service"
    if check_port; then
        log "Port $PORT is in use, stopping existing service"
        ./stop.sh 2>&1 | tee -a "$LOG_FILE" || true
        sleep 2
    else
        log "No existing service running"
    fi

    # Start service
    section "Step 2: Start New Service"
    log "Starting service with new API key..."
    export GOOGLE_API_KEY="$API_KEY"
    nohup python3 server.py > logs/server.log 2>&1 &
    SERVER_PID=$!
    log "Service started with PID: $SERVER_PID"

    # Wait for service to be ready
    log "Waiting for service to be ready..."
    sleep 3

    max_attempts=30
    attempt=0
    while [ $attempt -lt $max_attempts ]; do
        # Use HTTP health check for more reliable detection
        health_response=$(curl -s -w "%{http_code}" "${BASE_URL}/health" 2>&1)
        http_code=$(echo "$health_response" | tail -c 3)

        if [ "$http_code" == "200" ]; then
            success "Service is ready and responding"
            break
        else
            if [ $((attempt % 5)) -eq 0 ]; then
                log "Waiting for service... ($((attempt+1))/$max_attempts)"
            fi
            sleep 1
            attempt=$((attempt+1))
        fi
    done

    if ! check_port; then
        error "Service failed to start after $max_attempts attempts"
        exit 1
    fi

    # Run tests
    section "Step 3: Running Tests"

    total_tests=0
    passed_tests=0

    # Test all interfaces
    section "Step 3: Running Tests"

    # Run each test, track results
    test_health && passed_tests=$((passed_tests+1))
    total_tests=$((total_tests+1))
    sleep 1

    test_models && passed_tests=$((passed_tests+1))
    total_tests=$((total_tests+1))
    sleep 1

    test_chat_completions && passed_tests=$((passed_tests+1))
    total_tests=$((total_tests+1))
    sleep 1

    test_streaming && passed_tests=$((passed_tests+1))
    total_tests=$((total_tests+1))

    # Generate report
    section "Test Summary Report"
    echo "Total Tests: $total_tests" | tee -a "$LOG_FILE"
    echo "Passed: $passed_tests" | tee -a "$LOG_FILE"
    echo "Failed: $((total_tests - passed_tests))" | tee -a "$LOG_FILE"

    if [ $passed_tests -eq $total_tests ]; then
        success "All tests passed! 🎉"
        exit_code=0
    else
        error "Some tests failed. Please check the logs."
        # Keep service running for debugging if tests fail
        warn "Service is still running for debugging. Use './stop.sh' to stop it."
        exit_code=1
    fi

    log "Full test report available at: $LOG_FILE"
    log "Server logs available at: logs/server.log"
    log "Tests completed at $(date)"

    exit $exit_code
}

# ==================== Run Main ====================
main "$@"
```

## 脚本说明

这是一个完整的自动化测试脚本 (`test_all.sh`),具有以下功能:

### 📋 主要功能
1. **自动管理服务**: 停止现有服务,启动新服务
2. **四组核心测试**:
   - 健康检查 (`/health`)
   - 模型列表 (`/v1/models`)
   - 聊天补全 - 非流式 (`/v1/chat/completions`)
   - 聊天补全 - 流式 (`/v1/chat/completions?stream=true`)
3. **详细日志记录**: 所有测试步骤和结果保存到 `logs/test_report.log`
4. **彩色输出**: 不同级别的日志使用不同颜色
5. **测试报告**: 自动计算通过率,给出明确结果

### 🚀 使用方法

```bash
# 赋予执行权限
chmod +x test_all.sh

# 运行测试
./test_all.sh
```

### 📊 输出示例

```
============================================================
OpenAI Proxy Service - Automated Test Suite
============================================================

[INFO] Starting tests at 2026-04-26 21:15:00
[INFO] Project directory: /Users/zgh/Desktop/workspace/Toopenapi
[INFO] API Key: AIzaSyAzEnf92...
...
============================================================
Test Summary Report
============================================================

Total Tests: 4
Passed: 4
Failed: 0
[SUCCESS] All tests passed! 🎉
```

### 📝 日志文件
- 测试日志: `logs/test_report.log`
- 服务日志: `logs/server.log`

这个脚本实现了完整的自动化测试流程,可以快速验证服务是否工作正常!
