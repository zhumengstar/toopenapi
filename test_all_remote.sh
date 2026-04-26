#!/bin/bash
# ============================================================
# OpenAI Proxy Service - Remote Server Test Script
# This script performs comprehensive testing of all API interfaces
# Usage: ./test_all_remote.sh [API_KEY]
# ============================================================

set -e

# ==================== Configuration ====================
PORT=8787
DEFAULT_API_KEY="AIzaSyAzEnf92GCrLSbeFpqYtVzN0Y8gnye-j_s"
API_KEY="${1:-$DEFAULT_API_KEY}"
BASE_URL="http://localhost:${PORT}"
LOG_FILE="logs/test_report_$(date +%Y%m%d_%H%M%S).log"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVER_LOG="logs/server.log"

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
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

test_result() {
    echo -e "${CYAN}[TEST]${NC} $1" | tee -a "$LOG_FILE"
}

section() {
    echo "" | tee -a "$LOG_FILE"
    echo -e "${BLUE}============================================================${NC}" | tee -a "$LOG_FILE"
    echo -e "${BLUE}$1${NC}" | tee -a "$LOG_FILE"
    echo -e "${BLUE}============================================================${NC}" | tee -a "$LOG_FILE"
    echo "" | tee -a "$LOG_FILE"
}

check_dependencies() {
    section "Checking Dependencies"

    local all_deps_ok=true

    if command -v python3 &> /dev/null; then
        local python_version=$(python3 --version 2>&1)
        success "Python3 found: $python_version"
    else
        error "Python3 not found. Please install Python3."
        all_deps_ok=false
    fi

    if command -v curl &> /dev/null; then
        local curl_version=$(curl --version | head -n 1)
        success "curl found: $curl_version"
    else
        error "curl not found. Please install curl."
        all_deps_ok=false
    fi

    if $all_deps_ok; then
        success "All dependencies are satisfied"
        return 0
    else
        error "Some dependencies are missing"
        return 1
    fi
}

check_port() {
    if lsof -i :$PORT &> /dev/null; then
        return 0
    else
        return 1
    fi
}

stop_existing_service() {
    section "Step 1: Stop Existing Service"

    if check_port; then
        warn "Port $PORT is in use, attempting to stop existing service"

        # Try graceful shutdown first
        pkill -f "python3.*server.py" 2>/dev/null || true
        sleep 2

        # Force kill if still running
        if check_port; then
            warn "Forcing kill of processes on port $PORT"
            lsof -t -i :$PORT | xargs kill -9 2>/dev/null || true
            sleep 1
        fi

        if check_port; then
            error "Failed to stop existing service"
            return 1
        else
            success "Existing service stopped"
        fi
    else
        log "No existing service running"
    fi

    return 0
}

# ==================== Test Functions ====================
test_health() {
    section "Test 1: Health Check Interface"

    test_result "Testing GET ${BASE_URL}/health"
    local start_time=$(date +%s)

    local response
    response=$(curl -s -w "\n%{http_code}" "${BASE_URL}/health" 2>&1)
    local http_code=$(echo "$response" | tail -n 1)
    local body=$(echo "$response" | sed '$d')
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))

    if [ "$http_code" == "200" ]; then
        success "✓ Health check successful (HTTP 200)"
        log "Response time: ${duration}s"

        # Extract and display key info
        local status=$(echo "$body" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('status', 'unknown'))" 2>/dev/null || echo "unknown")
        local google_reachable=$(echo "$body" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('google_api_reachable', False))" 2>/dev/null || echo "false")

        log "Status: $status"
        if [ "$google_reachable" == "True" ]; then
            success "✓ Google API is reachable"
            return 0
        else
            warn "⚠ Google API is not reachable (but service is healthy)"
            return 1
        fi
    else
        error "✗ Health check failed with HTTP code: $http_code"
        log "Response: $body"
        return 1
    fi
}

test_models() {
    section "Test 2: Model List Interface"

    test_result "Testing GET ${BASE_URL}/v1/models"
    local start_time=$(date +%s)

    local response
    response=$(curl -s -w "\n%{http_code}" "${BASE_URL}/v1/models" 2>&1)
    local http_code=$(echo "$response" | tail -n 1)
    local body=$(echo "$response" | sed '$d')
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))

    if [ "$http_code" == "200" ]; then
        success "✓ Model list retrieved successfully (HTTP 200)"
        log "Response time: ${duration}s"

        # Extract model count
        local model_count=$(echo "$body" | python3 -c "
import sys, json
d=json.load(sys.stdin)
data = d.get('data', [])
print(len(data) if isinstance(data, list) else 0)
" 2>/dev/null || echo "0")

        if [ "$model_count" -gt 0 ]; then
            success "✓ Retrieved $model_count models"

            # Show first 3 models
            log "Sample models:"
            echo "$body" | python3 -c "
import sys, json
d=json.load(sys.stdin)
models = d.get('data', [])[:3]
for i, m in enumerate(models, 1):
    print(f'  {i}. {m.get('id', 'unknown')} - {m.get('display_name', 'N/A')}')
" | tee -a "$LOG_FILE"

            return 0
        else
            warn "⚠ No models found in response"
            log "Response: $body"
            return 1
        fi
    else
        error "✗ Model list request failed with HTTP code: $http_code"
        log "Response: $body"
        return 1
    fi
}

test_chat_completions() {
    section "Test 3: Chat Completions (Non-Streaming)"

    test_result "Testing POST ${BASE_URL}/v1/chat/completions (stream=false)"
    local start_time=$(date +%s)

    local request_payload='{
        "model": "gemma-4-31b-it",
        "messages": [
            {"role": "user", "content": "Hello! Who are you?"}
        ],
        "stream": false,
        "max_tokens": 100
    }'

    local response
    response=$(curl -s -w "\n%{http_code}" "${BASE_URL}/v1/chat/completions" \
        -H "Content-Type: application/json" \
        -d "$request_payload" 2>&1)
    local http_code=$(echo "$response" | tail -n 1)
    local body=$(echo "$response" | sed '$d')
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))

    if [ "$http_code" == "200" ]; then
        success "✓ Chat completion successful (HTTP 200)"
        log "Response time: ${duration}s"

        # Validate OpenAI format
        local is_valid_format=$(echo "$body" | python3 -c "
import sys, json
try:
    d=json.load(sys.stdin)
    if d.get('object') == 'chat.completion' and 'choices' in d:
        print('yes')
    else:
        print('no')
except:
    print('no')
" 2>/dev/null || echo "no")

        if [ "$is_valid_format" == "yes" ]; then
            success "✓ Response format is correct OpenAI format"

            # Extract content preview
            local content_preview=$(echo "$body" | python3 -c "
import sys, json
d=json.load(sys.stdin)
try:
    content = d['choices'][0]['message']['content']
    print(content[:150] + '...' if len(content) > 150 else content)
except:
    print('Could not extract content')
" 2>/dev/null || echo "Error")

            log "Assistant response preview: $content_preview"

            # Extract usage info
            local usage=$(echo "$body" | python3 -c "
import sys, json
d=json.load(sys.stdin)
u = d.get('usage', {})
print(f'tokens={u.get('total_tokens', 'N/A')}, prompt={u.get('prompt_tokens', 'N/A')}, completion={u.get('completion_tokens', 'N/A')}')
" 2>/dev/null || echo "N/A")

            log "Usage: $usage"
            return 0
        else
            error "✗ Response format is not valid OpenAI format"
            log "Response: $body"
            return 1
        fi
    elif [ "$http_code" == "400" ]; then
        local error_msg=$(echo "$body" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('error', {}).get('message', 'Unknown error'))" 2>/dev/null || echo "Unknown error")
        error "✗ Chat completion failed: $error_msg"
        return 1
    elif [ "$http_code" == "403" ]; then
        error "✗ API key unauthorized or blocked. Please check API key."
        log "Response: $body"
        return 1
    else
        error "✗ Chat completion failed with HTTP code: $http_code"
        log "Response: $body"
        return 1
    fi
}

test_streaming() {
    section "Test 4: Chat Completions (Streaming/SSE)"

    test_result "Testing POST ${BASE_URL}/v1/chat/completions (stream=true)"
    local start_time=$(date +%s)

    local request_payload='{
        "model": "gemma-4-31b-it",
        "messages": [
            {"role": "user", "content": "Count to 5 quickly"}
        ],
        "stream": true,
        "max_tokens": 50
    }'

    # Use temporary file for streaming response
    local response_file="/tmp/stream_response_$$.txt"

    # Run curl in background
    curl -N -w "\n%{http_code}" "${BASE_URL}/v1/chat/completions" \
        -H "Content-Type: application/json" \
        -d "$request_payload" > "$response_file" 2>&1 &

    local curl_pid=$!
    sleep 8  # Wait for streaming to complete

    # Kill curl if still running
    if kill -0 $curl_pid 2>/dev/null; then
        kill $curl_pid 2>/dev/null || true
    fi

    # Wait for process to finish
    wait $curl_pid 2>/dev/null || true

    # Read response
    local response=$(cat "$response_file")
    local http_code=$(echo "$response" | tail -n 1)
    local body=$(cat "$response_file" | sed '$d')
    rm -f "$response_file"

    local end_time=$(date +%s)
    local duration=$((end_time - start_time))

    # Clean body by removing curl progress info
    local clean_body=$(echo "$body" | grep -v "^%" | grep -v "Dload" | grep -v "Total" | grep -v "^$")

    if [ -n "$clean_body" ]; then
        success "✓ Streaming response received"
        log "Stream duration: ${duration}s"

        # Check if it contains SSE format
        if echo "$clean_body" | grep -q "^data: "; then
            success "✓ SSE format is correct"

            # Count chunks
            local chunk_count=$(echo "$clean_body" | grep -c "^data: " || echo "0")
            log "Number of chunks: $chunk_count"

            # Check if contains [DONE]
            if echo "$clean_body" | grep -q "data: \[DONE\]"; then
                success "✓ Stream completed with [DONE] marker"

                # Show first few chunks
                log "Sample chunks:"
                echo "$clean_body" | grep "^data:" | head -n 3 | python3 -c "
import sys
for i, line in enumerate(sys.stdin, 1):
    if i <= 3:
        try:
            # Parse the JSON in the data line
            json_str = line.strip().replace('data: ', '')
            data = __import__('json').loads(json_str)
            # Show a preview
            content = data.get('choices', [{}])[0].get('delta', {}).get('content', '')
            print(f'  Chunk {i}: {content[:50]}...')
n        except:
            print(f'  Chunk {i}: {line.strip()[:60]}')
" | tee -a "$LOG_FILE"

                return 0
            else
                warn "⚠ Stream did not contain [DONE] marker (incomplete stream)"
                return 1
            fi
        else
            warn "⚠ Response does not seem to be in SSE format"
            log "Raw response: $clean_body"
            return 1
        fi
    else
        error "✗ No streaming response received"
        log "Response: $body"
        return 1
    fi
}

start_service() {
    section "Step 2: Start Service"

    log "Starting OpenAI Proxy Service..."
    log "Port: $PORT"
    log "API Key: ${API_KEY:0:20}..."

    export GOOGLE_API_KEY="$API_KEY"

    # Create logs directory
    mkdir -p logs

    # Stop any existing service
    pkill -f "python3.*server.py" 2>/dev/null || true
    sleep 2

    # Start service in background
    nohup python3 server.py > "$SERVER_LOG" 2>&1 &
    local server_pid=$!

    log "Service started with PID: $server_pid"
    echo "$server_pid" > /tmp/openai_proxy.pid

    # Wait for service to be ready
    log "Waiting for service to be ready..."
    local max_attempts=30
    local attempt=0

    while [ $attempt -lt $max_attempts ]; do
        local health_response=$(curl -s -w "%{http_code}" "${BASE_URL}/health" 2>&1)
        local http_code=$(echo "$health_response" | tail -c 3)

        if [ "$http_code" == "200" ]; then
            success "✓ Service is ready and responding"
            return 0
        fi

        if [ $((attempt % 10)) -eq 0 ]; then
            log "Waiting... ($((attempt+1))/$max_attempts)"
        fi

        sleep 1
        attempt=$((attempt+1))
    done

    error "✗ Service failed to start after $max_attempts attempts"
    error "Check logs: $SERVER_LOG"
    return 1
}

# ==================== Main Script ====================
main() {
    cd "$PROJECT_DIR"

    section "OpenAI Proxy Service - Remote Server Test Suite"
    log "Starting tests at $(date)"
    log "Server: 35.208.9.0:$PORT"
    log "API Key: ${API_KEY:0:20}..."
    log "Test log: $LOG_FILE"

    # Create logs directory
    mkdir -p logs

    # Clear previous log
    > "$LOG_FILE"

    # Step 0: Check dependencies
    if ! check_dependencies; then
        error "Dependencies check failed. Please install required packages."
        exit 1
    fi

    # Step 1: Stop existing service
    if ! stop_existing_service; then
        exit 1
    fi

    # Step 2: Start service
    if ! start_service; then
        exit 1
    fi

    # Wait a moment for service to stabilize
    sleep 2

    # Step 3: Run all tests
    section "Step 3: Running Tests"

    local total_tests=0
    local passed_tests=0
    local failed_tests=0

    # Test 1: Health
    total_tests=$((total_tests+1))
    if test_health 2>&1 | tee -a "$LOG_FILE"; then
        passed_tests=$((passed_tests+1))
        log "✓ Test 1 PASSED"
    else
        failed_tests=$((failed_tests+1))
        error "✗ Test 1 FAILED"
    fi
    echo "" | tee -a "$LOG_FILE"
    sleep 1

    # Test 2: Models
    total_tests=$((total_tests+1))
    if test_models 2>&1 | tee -a "$LOG_FILE"; then
        passed_tests=$((passed_tests+1))
        log "✓ Test 2 PASSED"
    else
        failed_tests=$((failed_tests+1))
        error "✗ Test 2 FAILED"
    fi
    echo "" | tee -a "$LOG_FILE"
    sleep 1

    # Test 3: Chat Completions
    total_tests=$((total_tests+1))
    if test_chat_completions 2>&1 | tee -a "$LOG_FILE"; then
        passed_tests=$((passed_tests+1))
        log "✓ Test 3 PASSED"
    else
        failed_tests=$((failed_tests+1))
        error "✗ Test 3 FAILED"
    fi
    echo "" | tee -a "$LOG_FILE"
    sleep 1

    # Test 4: Streaming
    total_tests=$((total_tests+1))
    if test_streaming 2>&1 | tee -a "$LOG_FILE"; then
        passed_tests=$((passed_tests+1))
        log "✓ Test 4 PASSED"
    else
        failed_tests=$((failed_tests+1))
        error "✗ Test 4 FAILED"
    fi
    echo "" | tee -a "$LOG_FILE"

    # Generate final report
    section "Test Summary Report"

    log "Test execution completed at $(date)"

    echo -e "${MAGENTA}══════════════════════════════════════════════════════════${NC}" | tee -a "$LOG_FILE"
    echo -e "${MAGENTA}  Total Tests: ${total_tests}${NC}" | tee -a "$LOG_FILE"
    echo -e "${GREEN}  Passed: ${passed_tests}${NC}" | tee -a "$LOG_FILE"
    echo -e "${RED}  Failed: ${failed_tests}${NC}" | tee -a "$LOG_FILE"
    echo -e "${MAGENTA}══════════════════════════════════════════════════════════${NC}" | tee -a "$LOG_FILE"

    if [ $passed_tests -eq $total_tests ]; then
        success "🎉 All tests passed! 🎉"

        # Print service info
        section "Service Information"
        log "Service is running at: http://${EXTERNAL_IP:-35.208.9.0}:$PORT"
        log "OpenAI Compatible Base URL: http://${EXTERNAL_IP:-35.208.9.0}:$PORT/v1"
        log "Health Check: http://${EXTERNAL_IP:-35.208.9.0}:$PORT/health"
        log "Model List: http://${EXTERNAL_IP:-35.208.9.0}:$PORT/v1/models"

        exit 0
    else
        error "❌ Some tests failed. Please review the logs."
        warn "Service is still running for debugging."
        echo "" | tee -a "$LOG_FILE"
        log "Check logs for details:"
        log "  - Test log: $LOG_FILE"
        log "  - Server log: $SERVER_LOG"

        exit 1
    fi
}

# Run main function
main "$@"
