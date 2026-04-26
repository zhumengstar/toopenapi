"""
Google AI (Gemma) to OpenAI Protocol Proxy Server
将 Google AI API 转换为 OpenAI 兼容格式的代理服务
默认端口: 8787
"""

import json
import os
import ssl
import time
import logging
import traceback
from datetime import datetime
from typing import Dict, Any, Optional, Generator
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# ==================== 配置 ====================
class Config:
    """应用配置"""
    PORT = int(os.getenv("PORT", "8787"))
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")  # 必须设置
    GOOGLE_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
    DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gemma-4-31b-it")
    CACHE_DURATION = int(os.getenv("CACHE_DURATION", "300"))  # 模型缓存时间（秒）
    REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "120"))  # 请求超时（秒）
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE = os.getenv("LOG_FILE", "/tmp/openai_proxy.log")
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")  # CORS 允许的源，* 表示全部
    MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))  # 最大重试次数
    SKIP_SSL_VERIFY = os.getenv("SKIP_SSL_VERIFY", "true").lower() == "true"

config = Config()

# ==================== SSL 配置 ====================
ssl_context = ssl.create_default_context()
if config.SKIP_SSL_VERIFY:
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

# ==================== 日志配置 ====================
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(config.LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==================== 模型缓存 ====================
_cached_models: Optional[Dict[str, Any]] = None
_cached_model_details: Dict[str, Dict[str, Any]] = {}  # 单个模型的详细信息缓存
_cache_time: float = 0


# ==================== 工具函数 ====================
def log_request(method: str, path: str, status: int, duration: float, error: str = None):
    """记录请求日志"""
    log_data = {
        "timestamp": datetime.now().isoformat(),
        "method": method,
        "path": path,
        "status": status,
        "duration_ms": round(duration * 1000, 2)
    }
    if error:
        log_data["error"] = error
        logger.error(f"Request failed: {json.dumps(log_data)}")
    else:
        logger.info(f"Request: {json.dumps(log_data)}")


def clean_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    """移除值为 None 的键"""
    return {k: v for k, v in d.items() if v is not None}


def get_models_list() -> Dict[str, Any]:
    """从 Google AI API 获取模型列表（带缓存）"""
    global _cached_models, _cache_time
    
    current_time = time.time()
    
    # 检查缓存
    if _cached_models is not None and (current_time - _cache_time) < config.CACHE_DURATION:
        logger.debug("Using cached models list")
        return _cached_models
    
    try:
        api_url = f"{config.GOOGLE_API_BASE}/models?key={config.GOOGLE_API_KEY}"
        req = Request(api_url, method="GET")
        
        with urlopen(req, timeout=30, context=ssl_context) as response:
            google_response = json.loads(response.read().decode())
            
            models_data = []
            for model in google_response.get("models", []):
                model_name = model.get("name", "").replace("models/", "")
                
                # 列表接口不返回 inputTokenLimit，只包含基本信息
                model_item = {
                    "id": model_name,
                    "object": "model",
                    "created": parse_timestamp(model.get("createTime")),
                    "owned_by": model.get("publisher", "google"),
                    "permission": [],
                    "root": model_name,
                    "display_name": model.get("displayName"),
                    "description": model.get("description"),
                    "version": model.get("version"),
                }
                # 移除 None 值
                models_data.append(clean_dict(model_item))
            
            _cached_models = {
                "object": "list",
                "data": models_data
            }
            _cache_time = current_time
            
            logger.info(f"Fetched {len(models_data)} models from Google API")
            return _cached_models
            
    except Exception as e:
        logger.error(f"Failed to fetch models: {e}")
        if _cached_models is not None:
            logger.warning("Using stale cache due to fetch failure")
            return _cached_models
        return {"object": "list", "data": []}


def get_model_details(model_id: str) -> Optional[Dict[str, Any]]:
    """获取单个模型的详细信息，直接从原生接口获取上下文大小"""
    global _cached_model_details
    
    # 检查缓存
    if model_id in _cached_model_details:
        return _cached_model_details[model_id]
    
    try:
        # 直接从 Google API 获取单个模型详细信息（包含 inputTokenLimit）
        api_url = f"{config.GOOGLE_API_BASE}/models/{model_id}?key={config.GOOGLE_API_KEY}"
        req = Request(api_url, method="GET")
        
        with urlopen(req, timeout=30, context=ssl_context) as response:
            model_info = json.loads(response.read().decode())
            
            # 构建详情字典，只包含有值的字段
            details = {
                "id": model_id,
                "object": "model",
                "created": parse_timestamp(model_info.get("createTime")),
                "owned_by": model_info.get("publisher", "google"),
                "permission": [],
                "root": model_id,
                "display_name": model_info.get("displayName"),
                "description": model_info.get("description"),
                "version": model_info.get("version"),
                "context_window": model_info.get("inputTokenLimit"),
                "max_input_tokens": model_info.get("inputTokenLimit"),
                "max_output_tokens": model_info.get("outputTokenLimit"),
                "supported_methods": model_info.get("supportedGenerationMethods"),
                "temperature": model_info.get("temperature"),
                "top_p": model_info.get("topP"),
                "top_k": model_info.get("topK"),
            }
            
            # 移除 None 值
            details = clean_dict(details)
            
            _cached_model_details[model_id] = details
            return details
            
    except Exception as e:
        logger.error(f"Failed to fetch model details for {model_id}: {e}")
        return None


def parse_timestamp(timestamp_str: str) -> int:
    """解析 ISO 格式时间戳"""
    if not timestamp_str:
        return 1700000000
    try:
        # 尝试解析 "2024-01-01T00:00:00.000Z" 格式
        if "." in timestamp_str:
            ts = timestamp_str.split(".")[0]
        else:
            ts = timestamp_str.rstrip("Z")
        return int(datetime.fromisoformat(ts.replace("T", " ")).timestamp())
    except:
        return 1700000000


def convert_openai_to_google(request_body: Dict[str, Any]) -> Dict[str, Any]:
    """将 OpenAI 格式请求转换为 Google AI 格式"""
    model = request_body.get("model", config.DEFAULT_MODEL)
    messages = request_body.get("messages", [])
    
    # 处理 system 消息（放在第一条 user 消息之前）
    system_content = ""
    processed_messages = []
    
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        
        if role == "system":
            system_content += content + "\n"
        else:
            processed_messages.append(msg)
    
    # 构建 contents
    contents = []
    
    # 添加 system 提示
    if system_content:
        contents.append({
            "role": "user",
            "parts": [{"text": system_content.strip()}]
        })
    
    # 添加对话消息
    for msg in processed_messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        
        # 转换角色
        google_role = "model" if role in ("model", "assistant") else "user"
        
        contents.append({
            "role": google_role,
            "parts": [{"text": content}]
        })
    
    # 构建 generationConfig
    generation_config = {
        "temperature": request_body.get("temperature", 0.9),
        "maxOutputTokens": request_body.get("max_tokens", 2048),
        "topP": request_body.get("top_p", 0.95),
    }
    
    # 添加停止序列
    if "stop" in request_body:
        stop = request_body["stop"]
        if isinstance(stop, str):
            generation_config["stopSequences"] = [stop]
        elif isinstance(stop, list):
            generation_config["stopSequences"] = stop
    
    return {
        "contents": contents,
        "generationConfig": generation_config
    }, model


def convert_google_to_openai(google_response: Dict[str, Any], model: str) -> Dict[str, Any]:
    """将 Google AI 响应转换为 OpenAI 格式"""
    response_content = ""
    
    try:
        candidates = google_response.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            response_content = "".join(part.get("text", "") for part in parts)
    except (KeyError, IndexError) as e:
        logger.error(f"Failed to parse response: {e}")
        response_content = "Error: Unable to parse response"
    
    usage = google_response.get("usageMetadata", {})
    
    return {
        "id": f"chatcmpl-{int(time.time() * 1000)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": response_content
            },
            "finish_reason": "stop"
        }],
        "usage": {
            "prompt_tokens": usage.get("promptTokenCount", 0),
            "completion_tokens": usage.get("candidatesTokenCount", 0),
            "total_tokens": usage.get("totalTokenCount", 0)
        }
    }


def convert_google_to_openai_stream(google_response: Dict[str, Any], model: str, chunk_id: int = 0) -> Dict[str, Any]:
    """将 Google AI 响应转换为 OpenAI 流式格式"""
    response_content = ""
    
    try:
        candidates = google_response.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            response_content = "".join(part.get("text", "") for part in parts)
    except (KeyError, IndexError):
        response_content = ""
    
    chunk_id_str = f"chatcmpl-{int(time.time() * 1000)}"
    
    return {
        "id": chunk_id_str,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "delta": {
                "content": response_content
            },
            "finish_reason": "stop"
        }]
    }


def generate_sse_event(data: Dict[str, Any]) -> Generator[str, None, None]:
    """生成 SSE 格式的事件流"""
    yield f"data: {json.dumps(data)}\n\n"


# ==================== HTTP 处理器 ====================
class ProxyHandler(BaseHTTPRequestHandler):
    
    def _set_headers(self, status: int = 200, cors: bool = True):
        """设置响应头"""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        if cors:
            self.send_header("Access-Control-Allow-Origin", config.CORS_ORIGINS)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
    
    def _send_json(self, data: Dict[str, Any], status: int = 200, stream: bool = False):
        """发送 JSON 响应"""
        self.send_response(status)
        
        if stream:
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
        else:
            self.send_header("Content-Type", "application/json")
        
        self.send_header("Access-Control-Allow-Origin", config.CORS_ORIGINS)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        
        if stream:
            self.wfile.write(b"")
        else:
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
    
    def _send_error(self, message: str, status: int = 500, error_type: str = "server_error"):
        """发送错误响应"""
        self._set_headers(status)
        error_response = {
            "error": {
                "message": message,
                "type": error_type,
                "code": status
            }
        }
        self.wfile.write(json.dumps(error_response, ensure_ascii=False).encode())
    
    def _parse_json_body(self) -> Optional[Dict[str, Any]]:
        """解析 JSON 请求体"""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            return {}
        try:
            body = self.rfile.read(content_length)
            return json.loads(body.decode())
        except json.JSONDecodeError:
            self._send_error("Invalid JSON body", 400, "invalid_request_error")
            return None
    
    def _get_api_key(self, request_body: Dict[str, Any] = None) -> str:
        """获取 API Key，优先级：请求体 > Header > 环境变量"""
        # 1. 从请求体获取
        if request_body and request_body.get("api_key"):
            return request_body["api_key"]
        
        # 2. 从 Authorization Header 获取
        auth_header = self.headers.get("Authorization", "")
        api_key = auth_header.replace("Bearer ", "").strip()
        if api_key:
            return api_key
        
        # 3. 从环境变量获取
        if config.GOOGLE_API_KEY:
            return config.GOOGLE_API_KEY
        
        # 4. 无可用 key
        return ""
    
    def do_OPTIONS(self):
        """处理 CORS 预检请求"""
        self._set_headers(200)
        self.wfile.write(b"")
    
    def do_GET(self):
        """处理 GET 请求"""
        start_time = time.time()
        path = self.path
        status = 200
        
        try:
            if path in ("/", "/v1"):
                # 服务状态
                models = get_models_list()
                self._send_json({
                    "status": "ok",
                    "service": "Google AI → OpenAI Protocol Proxy",
                    "version": "1.0.0",
                    "uptime": time.time() - start_time,
                    "endpoints": {
                        "chat_completions": "/v1/chat/completions",
                        "models": "/v1/models",
                        "health": "/health"
                    },
                    "model_count": len(models.get("data", []))
                })
                
            elif path == "/v1/models":
                # 获取模型列表
                self._send_json(get_models_list())
                
            elif path.startswith("/v1/models/"):
                # 获取单个模型详情
                model_id = path.replace("/v1/models/", "")
                details = get_model_details(model_id)
                if details:
                    self._send_json(details)
                else:
                    # 如果获取失败，尝试从列表中返回基本信息
                    models = get_models_list()
                    model_data = next((m for m in models.get("data", []) if m["id"] == model_id), None)
                    if model_data:
                        self._send_json(model_data)
                    else:
                        status = 404
                        self._send_error(f"Model '{model_id}' not found", 404, "not_found")
                
            elif path == "/health":
                # 健康检查
                self._send_json({
                    "status": "healthy",
                    "timestamp": datetime.now().isoformat(),
                    "google_api_reachable": self._check_google_api()
                })
                
            elif path == "/v1/models/count":
                # 获取模型数量
                models = get_models_list()
                self._send_json({
                    "count": len(models.get("data", [])),
                    "models": [m["id"] for m in models.get("data", [])]
                })
                
            else:
                status = 404
                self._send_error("Not found", 404, "not_found")
                
        except Exception as e:
            logger.error(f"GET {path} failed: {e}\n{traceback.format_exc()}")
            status = 500
            self._send_error(str(e), 500)
        finally:
            log_request("GET", path, status, time.time() - start_time)
    
    def _check_google_api(self) -> bool:
        """检查 Google API 是否可达"""
        try:
            req = Request(f"{config.GOOGLE_API_BASE}/models?key={config.GOOGLE_API_KEY}", method="GET")
            with urlopen(req, timeout=10, context=ssl_context):
                return True
        except:
            return False
    
    def do_POST(self):
        """处理 POST 请求"""
        start_time = time.time()
        path = self.path
        status = 200
        
        try:
            if path not in ("/v1/chat/completions", "/chat/completions"):
                self._send_error("Not found", 404, "not_found")
                return
            
            request_body = self._parse_json_body()
            if request_body is None:
                return
            
            api_key = self._get_api_key(request_body)
            if not api_key:
                self._send_error("API key is required", 401, "authentication_error")
                return
            
            google_request, model = convert_openai_to_google(request_body)
            
            # 检查是否需要流式响应
            stream = request_body.get("stream", False)
            
            if stream:
                self._handle_stream_request(api_key, model, google_request)
            else:
                self._handle_normal_request(api_key, model, google_request)
            
        except Exception as e:
            logger.error(f"POST {path} failed: {e}\n{traceback.format_exc()}")
            status = 500
            self._send_error(str(e), 500)
        finally:
            log_request("POST", path, status, time.time() - start_time)
    
    def _handle_normal_request(self, api_key: str, model: str, google_request: Dict[str, Any]):
        """处理普通请求"""
        api_url = f"{config.GOOGLE_API_BASE}/models/{model}:generateContent?key={api_key}"
        
        try:
            req = Request(
                api_url,
                data=json.dumps(google_request, ensure_ascii=False).encode(),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            
            with urlopen(req, timeout=config.REQUEST_TIMEOUT, context=ssl_context) as response:
                google_response = json.loads(response.read().decode())
                openai_response = convert_google_to_openai(google_response, model)
                self._send_json(openai_response)
                
        except HTTPError as e:
            try:
                error_body = json.loads(e.read().decode())
                error_message = error_body.get("error", {}).get("message", str(e))
            except:
                error_message = str(e)
            self._send_error(error_message, e.code, "api_error")
            
        except URLError as e:
            self._send_error(f"Request failed: {e.reason}", 500, "api_error")
    
    def _handle_stream_request(self, api_key: str, model: str, google_request: Dict[str, Any]):
        """处理流式请求"""
        api_url = f"{config.GOOGLE_API_BASE}/models/{model}:generateContent?key={api_key}"
        
        try:
            req = Request(
                api_url,
                data=json.dumps(google_request, ensure_ascii=False).encode(),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            
            with urlopen(req, timeout=config.REQUEST_TIMEOUT, context=ssl_context) as response:
                google_response = json.loads(response.read().decode())
                openai_response = convert_google_to_openai_stream(google_response, model)
                
                # 发送 SSE 响应
                self._set_headers(200, cors=True)
                
                # 发送首个 chunk
                self.wfile.write(f"data: {json.dumps(openai_response, ensure_ascii=False)}\n\n".encode())
                
                # 发送结束信号
                self.wfile.write(b"data: [DONE]\n\n")
                
        except (HTTPError, URLError) as e:
            self._send_error(str(e), 500, "api_error")
    
    def log_message(self, format, *args):
        """静默日志（使用自定义日志）"""
        pass


# ==================== 主函数 ====================
def print_banner():
    """打印启动横幅"""
    banner = f"""
    ╭─────────────────────────────────────────────────────────────╮
    │           Google AI → OpenAI Protocol Proxy                │
    ╰─────────────────────────────────────────────────────────────╯

    ┌─ Config ──────────────────────────────────────────────────┐
    │  Port:         {config.PORT:<46}│
    │  API Key:      {(config.GOOGLE_API_KEY[:20] + '...') if config.GOOGLE_API_KEY else 'Not Set':<30}│
    │  Default:       {config.DEFAULT_MODEL:<46}│
    │  Timeout:      {config.REQUEST_TIMEOUT}s                                        │
    │  SSL Verify:   {str(config.SKIP_SSL_VERIFY):<46}│
    └─────────────────────────────────────────────────────────────┘

    ┌─ Endpoints ───────────────────────────────────────────────┐
    │  POST  /v1/chat/completions   Chat completion             │
    │  GET   /v1/models             List models                 │
    │  GET   /v1/models/{{id}}      Model details                │
    │  GET   /health                Health check                │
    │  GET   /                      Service info                │
    └─────────────────────────────────────────────────────────────┘
    """
    print(banner)


def main():
    """启动服务"""
    print_banner()
    
    if config.GOOGLE_API_KEY:
        print(f"   API Key:      {config.GOOGLE_API_KEY[:20]}... (from env)")
    else:
        print("   API Key:      Not set (from request)")
    
    logger.info(f"Starting server on port {config.PORT}")
    
    server = HTTPServer(("0.0.0.0", config.PORT), ProxyHandler)
    
    try:
        logger.info(f"Server started at http://0.0.0.0:{config.PORT}")
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
        server.shutdown()


if __name__ == "__main__":
    main()
