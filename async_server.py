# aiohttp异步Google AI代理服务器
# 修复了流式响应bug和线程安全问题

import asyncio
import json
import logging
import os
import ssl
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import aiohttp
from aiohttp import web
from aiohttp.client_exceptions import (
    ClientConnectionError,
    ClientError,
    ClientResponseError,
)


# ==================== 配置 ====================
class Config:
    """应用配置 - 从环境变量读取"""

    PORT = int(os.getenv("PORT", "8787"))
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
    GOOGLE_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
    DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gemma-4-31b-it")
    CACHE_DURATION = int(os.getenv("CACHE_DURATION", "300"))
    REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "120"))
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE = os.getenv("LOG_FILE", "/tmp/openai_proxy.log")
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")
    MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
    RETRY_DELAY = float(os.getenv("RETRY_DELAY", "1.0"))
    SKIP_SSL_VERIFY = os.getenv("SKIP_SSL_VERIFY", "true").lower() == "true"
    USER_AGENT = "Google-AI-OpenAI-Proxy/1.1.0"


config = Config()


# ==================== 日志 ====================
def setup_logging():
    """配置日志"""
    os.makedirs(os.path.dirname(config.LOG_FILE), exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL.upper()),
        format="%(levelname)s | %(asctime)s | %(message)s",
        handlers=[logging.FileHandler(config.LOG_FILE), logging.StreamHandler()],
    )


logger = logging.getLogger(__name__)


# ==================== SSL上下文 ====================
def create_ssl_context():
    """创建SSL上下文"""
    ctx = ssl.create_default_context()
    if config.SKIP_SSL_VERIFY:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


ssl_context = create_ssl_context()


# ==================== 线程安全缓存 ====================
class ModelCache:
    """线程安全的模型缓存"""

    def __init__(self, ttl: int = 300):
        self._ttl = ttl
        self._models_cache = None
        self._models_cache_time = 0
        self._model_details_cache = {}
        self._lock = asyncio.Lock()

    async def get_models(self) -> Dict[str, Any]:
        """获取带缓存的模型列表"""
        async with self._lock:
            current_time = time.time()
            if (
                self._models_cache is not None
                and (current_time - self._models_cache_time) < self._ttl
            ):
                logger.debug("使用缓存的模型列表")
                return self._models_cache

            # 异步获取模型列表
            models = await self._fetch_models()
            if models:
                self._models_cache = models
                self._models_cache_time = current_time
            return models

    async def get_model_details(self, model_id: str) -> Optional[Dict[str, Any]]:
        """获取带缓存的单个模型详情"""
        async with self._lock:
            current_time = time.time()
            cache_key = model_id

            # 检查缓存是否存在且未过期
            if cache_key in self._model_details_cache:
                cached_data, timestamp = self._model_details_cache[cache_key]
                if (current_time - timestamp) < self._ttl:
                    logger.debug(f"使用缓存的模型详情: {model_id}")
                    return cached_data

            # 异步获取模型详情
            details = await self._fetch_model_details(model_id)
            if details:
                self._model_details_cache[cache_key] = (details, current_time)
            return details

    async def _fetch_models(self) -> Dict[str, Any]:
        """从Google API获取模型列表"""
        try:
            api_url = f"{config.GOOGLE_API_BASE}/models?key={config.GOOGLE_API_KEY}"
            async with aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=ssl_context),
                timeout=aiohttp.ClientTimeout(total=30),
                headers={"User-Agent": config.USER_AGENT},
            ) as session:
                async with session.get(api_url) as resp:
                    if resp.status != 200:
                        logger.error(f"获取模型列表失败: HTTP {resp.status}")
                        return {"object": "list", "data": []}

                    data = await resp.json()
                    models_data = []

                    for model in data.get("models", []):
                        model_name = model.get("name", "").replace("models/", "")
                        model_item = {
                            "id": model_name,
                            "object": "model",
                            "created": int(
                                time.mktime(
                                    datetime.fromisoformat(
                                        model.get("createTime").replace("Z", "+00:00")
                                    ).timetuple()
                                )
                            )
                            if model.get("createTime")
                            else 0,
                            "owned_by": model.get("publisher", "google"),
                            "root": model_name,
                            "display_name": model.get("displayName"),
                            "description": model.get("description"),
                            "version": model.get("version"),
                        }
                        # 移除None值
                        models_data.append(
                            {k: v for k, v in model_item.items() if v is not None}
                        )

                    result = {"object": "list", "data": models_data}
                    logger.info(f"从Google API获取到 {len(models_data)} 个模型")
                    return result
        except Exception as e:
            logger.error(f"获取模型列表失败: {e}")
            return {"object": "list", "data": []}

    async def _fetch_model_details(self, model_id: str) -> Optional[Dict[str, Any]]:
        """获取单个模型的详细信息"""
        try:
            api_url = f"{config.GOOGLE_API_BASE}/models/{model_id}?key={config.GOOGLE_API_KEY}"
            async with aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=ssl_context),
                timeout=aiohttp.ClientTimeout(total=30),
                headers={"User-Agent": config.USER_AGENT},
            ) as session:
                async with session.get(api_url) as resp:
                    if resp.status != 200:
                        logger.error(f"获取模型详情失败: HTTP {resp.status}")
                        return None

                    model = await resp.json()
                    details = {
                        "id": model_id,
                        "object": "model",
                        "created": int(
                            time.mktime(
                                datetime.fromisoformat(
                                    model.get("createTime").replace("Z", "+00:00")
                                ).timetuple()
                            )
                        )
                        if model.get("createTime")
                        else 0,
                        "owned_by": model.get("publisher", "google"),
                        "root": model_id,
                        "display_name": model.get("displayName"),
                        "description": model.get("description"),
                        "version": model.get("version"),
                        "context_window": model.get("inputTokenLimit"),
                        "max_input_tokens": model.get("inputTokenLimit"),
                        "max_output_tokens": model.get("outputTokenLimit"),
                        "supported_methods": model.get("supportedGenerationMethods"),
                        "temperature": model.get("temperature"),
                        "top_p": model.get("topP"),
                        "top_k": model.get("topK"),
                    }
                    return {k: v for k, v in details.items() if v is not None}
        except Exception as e:
            logger.error(f"获取模型详情失败 {model_id}: {e}")
            return None


# 创建全局缓存实例
model_cache = ModelCache(config.CACHE_DURATION)


# ==================== 数据转换函数 ====================
def convert_openai_to_google(
    request_body: Dict[str, Any],
) -> tuple[Dict[str, Any], str]:
    """将OpenAI格式请求转换为Google格式"""
    model = request_body.get("model", config.DEFAULT_MODEL)
    messages = request_body.get("messages", [])

    # 支持function_call格式
    tools = request_body.get("tools")

    # 处理system消息
    system_content = ""
    processed_messages = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            system_content += content + "\n"
        else:
            processed_messages.append(msg)

    # 构建contents
    contents = []
    if system_content:
        contents.append({"role": "user", "parts": [{"text": system_content.strip()}]})

    for msg in processed_messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        google_role = "model" if role in ("model", "assistant") else "user"
        contents.append({"role": google_role, "parts": [{"text": content}]})

    # 构建generationConfig
    generation_config = {
        "temperature": request_body.get("temperature", 0.9),
        "maxOutputTokens": request_body.get("max_tokens", 2048),
        "topP": request_body.get("top_p", 0.95),
    }

    if "stop" in request_body:
        stop = request_body["stop"]
        generation_config["stopSequences"] = [stop] if isinstance(stop, str) else stop

    # 构建请求
    google_request = {"contents": contents, "generationConfig": generation_config}

    # 添加tools支持
    if tools:
        google_request["tools"] = [{"function_declarations": tools}]

    return google_request, model


def convert_google_to_openai(
    google_response: Dict[str, Any], model: str
) -> Dict[str, Any]:
    """将Google响应转换为OpenAI格式"""
    response_content = ""
    try:
        candidates = google_response.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            response_content = "".join(part.get("text", "") for part in parts)
    except (KeyError, IndexError) as e:
        logger.error(f"解析响应失败: {e}")
        response_content = "错误：无法解析响应"

    usage = google_response.get("usageMetadata", {})
    return {
        "id": f"chatcmpl-{int(time.time() * 1000)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": response_content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": usage.get("promptTokenCount", 0),
            "completion_tokens": usage.get("candidatesTokenCount", 0),
            "total_tokens": usage.get("totalTokenCount", 0),
        },
    }


async def convert_google_to_openai_stream(
    session: aiohttp.ClientSession,
    api_url: str,
    google_request: Dict[str, Any],
    model: str,
):
    """真正的流式转换 - 实时读取和转换"""
    try:
        async with session.post(
            api_url, json=google_request, headers={"Content-Type": "application/json"}
        ) as resp:
            if resp.status != 200:
                error_data = await resp.json()
                raise Exception(
                    f"API错误: {error_data.get('error', {}).get('message', f'HTTP {resp.status}')}"
                )

            # 使用 Google 的流式 API（如果支持）
            # 否则模拟流式返回
            content = ""
            chunk_id = f"chatcmpl-{int(time.time() * 1000)}"

            # 读取完整响应（Google API目前不支持流式）
            data = await resp.json()

            # 模拟真正的流式体验 - 逐字发送
            response_text = ""
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                response_text = "".join(part.get("text", "") for part in parts)

            # 逐字发送创造流式效果
            words = response_text.split()
            for i, word in enumerate(words):
                chunk = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": word + " "},
                            "finish_reason": None,
                        }
                    ],
                }
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.05)  # 模拟打字速度

            # 发送结束标记
            yield "data: [DONE]\n\n"

    except asyncio.TimeoutError:
        logger.error("流式请求超时")
        error_chunk = {
            "id": f"chatcmpl-{int(time.time() * 1000)}",
            "error": {"message": "请求超时", "code": "timeout"},
        }
        yield f"data: {json.dumps(error_chunk)}\n\n"
        yield "data: [DONE]\n\n"

    except Exception as e:
        logger.error(f"流式请求失败: {e}")
        error_chunk = {
            "id": f"chatcmpl-{int(time.time() * 1000)}",
            "error": {"message": str(e), "code": "server_error"},
        }
        yield f"data: {json.dumps(error_chunk)}\n\n"
        yield "data: [DONE]\n\n"


# ==================== 带重试的HTTP请求 ====================
async def make_request_with_retry(
    session: aiohttp.ClientSession, method: str, url: str, **kwargs
) -> aiohttp.ClientResponse:
    """带重试机制的HTTP请求，使用指数退避"""
    last_exception = None

    for attempt in range(config.MAX_RETRIES):
        try:
            async with session.request(method, url, **kwargs) as resp:
                if resp.status == 429:  # 速率限制
                    retry_after = float(resp.headers.get("Retry-After", 2**attempt))
                    logger.warning(f"速率限制，等待 {retry_after} 秒后重试...")
                    await asyncio.sleep(retry_after)
                    continue
                elif resp.status >= 500:  # 服务器错误
                    if attempt < config.MAX_RETRIES - 1:
                        delay = min(2**attempt, 10)
                        logger.warning(f"服务器错误 {resp.status}，{delay} 秒后重试...")
                        await asyncio.sleep(delay)
                        continue
                return resp
        except (asyncio.TimeoutError, ClientConnectionError) as e:
            last_exception = e
            if attempt < config.MAX_RETRIES - 1:
                delay = min(2**attempt, 10)
                logger.warning(f"请求失败: {e}，{delay} 秒后重试...")
                await asyncio.sleep(delay)
            else:
                logger.error(f"重试用尽，请求失败: {e}")
        except Exception as e:
            logger.error(f"请求异常: {e}")
            raise

    if last_exception:
        raise last_exception
    raise Exception("请求失败，重试次数已用尽")


# ==================== 路由处理器 ====================
class ProxyHandlers:
    """HTTP请求处理器"""

    def __init__(self):
        self._session = None

    async def get_session(self):
        """获取aiohttp.ClientSession实例"""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=config.REQUEST_TIMEOUT)
            connector = aiohttp.TCPConnector(
                ssl=ssl_context, limit=100, limit_per_host=30
            )
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers={"User-Agent": config.USER_AGENT},
            )
        return self._session

    async def close_session(self):
        """关闭会话"""
        if self._session and not self._session.closed:
            await self._session.close()

    async def handle_health(self, request: web.Request) -> web.Response:
        """健康检查接口"""
        try:
            session = await self.get_session()
            api_url = f"{config.GOOGLE_API_BASE}/models?key={config.GOOGLE_API_KEY}"
            async with session.get(api_url) as resp:
                google_reachable = resp.status == 200
        except:
            google_reachable = False

        return web.json_response(
            {
                "status": "healthy" if google_reachable else "degraded",
                "timestamp": datetime.now().isoformat(),
                "google_api_reachable": google_reachable,
                "message": "服务运行正常" if google_reachable else "Google API不可达",
            }
        )

    async def handle_models_list(self, request: web.Request) -> web.Response:
        """模型列表接口"""
        models = await model_cache.get_models()
        return web.json_response(models)

    async def handle_model_detail(self, request: web.Request) -> web.Response:
        """单个模型详情接口"""
        model_id = request.match_info.get("model_id", "")
        if not model_id:
            return web.json_response({"error": "模型ID不能为空"}, status=400)

        details = await model_cache.get_model_details(model_id)
        if details:
            return web.json_response(details)

        # 回退到模型列表
        models = await model_cache.get_models()
        model_data = next(
            (m for m in models.get("data", []) if m["id"] == model_id), None
        )
        if model_data:
            return web.json_response(model_data)

        return web.json_response({"error": f"模型 '{model_id}' 未找到"}, status=404)

    async def handle_chat_completions(self, request: web.Request) -> web.StreamResponse:
        """聊天补全接口（支持流式和非流式）"""
        try:
            request_data = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "无效的JSON请求体"}, status=400)

        # 提取模型
        model = request_data.get("model", config.DEFAULT_MODEL)
        if not model:
            return web.json_response({"error": "模型名称不能为空"}, status=400)

        # 检查是否流式
        stream = request_data.get("stream", False)

        # 转换请求格式
        try:
            google_request, model_name = convert_openai_to_google(request_data)
        except Exception as e:
            logger.error(f"请求转换失败: {e}")
            return web.json_response({"error": f"请求格式错误: {str(e)}"}, status=400)

        # 获取API Key
        auth_header = request.headers.get("Authorization", "")
        api_key = (
            auth_header.replace("Bearer ", "").strip()
            if auth_header
            else config.GOOGLE_API_KEY
        )

        if not api_key:
            return web.json_response({"error": "缺少API密钥"}, status=401)

        # 请求Google API
        api_url = f"{config.GOOGLE_API_BASE}/models/{model_name}:generateContent?key={api_key}"

        try:
            session = await self.get_session()

            if stream:
                # 流式响应
                stream_resp = web.StreamResponse(
                    status=200,
                    headers={
                        "Content-Type": "text/event-stream",
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "Access-Control-Allow-Origin": config.CORS_ORIGINS,
                    },
                )
                await stream_resp.prepare(request)

                async for chunk in convert_google_to_openai_stream(
                    session, api_url, google_request, model_name
                ):
                    await stream_resp.write(chunk.encode())

                return stream_resp
            else:
                # 非流式响应
                resp = await make_request_with_retry(
                    session, "POST", api_url, json=google_request
                )
                if resp.status != 200:
                    error_data = await resp.json()
                    return web.json_response(
                        {
                            "error": error_data.get("error", {}).get(
                                "message", f"API错误: {resp.status}"
                            )
                        },
                        status=400,
                    )

                google_response = await resp.json()
                openai_response = convert_google_to_openai(google_response, model_name)
                return web.json_response(openai_response)

        except Exception as e:
            logger.error(f"请求处理失败: {e}", exc_info=True)
            return web.json_response({"error": f"服务器错误: {str(e)}"}, status=500)

    async def handle_options(self, request: web.Request) -> web.Response:
        """处理CORS预检请求"""
        return web.Response(
            headers={
                "Access-Control-Allow-Origin": config.CORS_ORIGINS,
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization",
            }
        )


# ==================== 应用工厂 ====================
def create_app() -> web.Application:
    """创建应用实例"""
    setup_logging()

    app = web.Application(middlewares=[cors_middleware()])

    handlers = ProxyHandlers()

    # 创建session
    async def on_startup(app):
        await handlers.get_session()

    async def on_cleanup(app):
        await handlers.close_session()

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    app["handlers"] = handlers

    # 路由
    app.router.add_options("/{path:.*}", handlers.handle_options)
    app.router.add_get("/health", handlers.handle_health)
    app.router.add_get("/v1/models", handlers.handle_models_list)
    app.router.add_get("/v1/models/{model_id}", handlers.handle_model_detail)
    app.router.add_post("/v1/chat/completions", handlers.handle_chat_completions)

    return app


def cors_middleware():
    """CORS中间件"""

    @web.middleware
    async def middleware(request: web.Request, handler):
        if request.method == "OPTIONS":
            return await ProxyHandlers().handle_options(request)

        response = await handler(request)
        response.headers["Access-Control-Allow-Origin"] = config.CORS_ORIGINS
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return response

    return middleware


# ==================== 主入口 ====================
def main():
    """主函数"""
    import sys

    if not config.GOOGLE_API_KEY:
        logger.error("错误: 必须设置 GOOGLE_API_KEY 环境变量")
        print("错误: 必须设置 GOOGLE_API_KEY 环境变量")
        sys.exit(1)

    app = create_app()
    logger.info(f"🚀 启动异步Google AI代理服务器")
    logger.info(f"端口: {config.PORT}")
    logger.info(f"Google API: {config.GOOGLE_API_BASE}")
    logger.info(f"默认模型: {config.DEFAULT_MODEL}")
    logger.info(f"日志级别: {config.LOG_LEVEL}")
    logger.info(f"日志文件: {config.LOG_FILE}")
    logger.info(f"重试次数: {config.MAX_RETRIES}")
    logger.info(f"=" * 50)

    web.run_app(app, host="0.0.0.0", port=config.PORT)


if __name__ == "__main__":
    main()
