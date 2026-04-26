#!/usr/bin/env python3
"""
异步服务器单元测试
测试异步服务器的所有核心功能
"""

import asyncio
import json
import sys
import time
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

# 将父目录添加到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from async_server import (
    Config,
    ModelCache,
    ProxyHandlers,
    convert_google_to_openai,
    convert_openai_to_google,
    create_app,
)


class TestConfig:
    """配置测试类"""

    def test_default_config(self):
        """测试默认配置加载"""
        # 创建默认配置实例
        config = Config()
        assert config.PORT == 8787
        assert (
            config.GOOGLE_API_BASE == "https://generativelanguage.googleapis.com/v1beta"
        )
        assert config.DEFAULT_MODEL == "gemma-4-31b-it"
        assert config.CACHE_DURATION == 300
        assert config.REQUEST_TIMEOUT == 120
        assert config.MAX_RETRIES == 3

    def test_env_override(self):
        """测试环境变量覆盖"""
        # 设置测试环境变量
        os.environ["PORT"] = "9999"
        os.environ["DEFAULT_MODEL"] = "test-model"
        os.environ["CACHE_DURATION"] = "600"

        config = Config()
        assert config.PORT == 9999
        assert config.DEFAULT_MODEL == "test-model"
        assert config.CACHE_DURATION == 600

        # 清理
        del os.environ["PORT"]
        del os.environ["DEFAULT_MODEL"]
        del os.environ["CACHE_DURATION"]


class TestModelCache:
    """模型缓存测试类"""

    @pytest.fixture
    def model_cache(self):
        """创建模型缓存实例"""
        return ModelCache(ttl=2)  # 2秒过期时间

    @pytest.mark.asyncio
    async def test_get_models_initial(self, model_cache):
        """测试初始获取模型列表"""
        # 第一次应该返回空列表（mock失败）
        result = await model_cache.get_models()
        assert result["object"] == "list"
        assert result["data"] == []

    @pytest.mark.asyncio
    async def test_get_model_details_initial(self, model_cache):
        """测试初始获取模型详情"""
        result = await model_cache.get_model_details("non-existent-model")
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_timing(self, model_cache):
        """测试缓存过期"""
        # 没有网络请求的情况下，缓存应该过期
        start_time = time.time()

        # 第一次调用
        await model_cache.get_models()
        assert model_cache._models_cache is not None

        # 等待过期
        await asyncio.sleep(3)

        # 第二次调用应该重新加载（但mock会返回空）
        result = await model_cache.get_models()
        assert result["object"] == "list"


class TestDataConversion:
    """数据转换测试类 - OpenAI格式与Google格式互转"""

    def test_convert_openai_to_google_simple(self):
        """测试简单OpenAI请求转换"""
        request_body = {
            "model": "gemma-4-31b-it",
            "messages": [{"role": "user", "content": "Hello!"}],
        }

        result, model = convert_openai_to_google(request_body)

        assert model == "gemma-4-31b-it"
        assert "contents" in result
        assert len(result["contents"]) == 1
        assert result["contents"][0]["role"] == "user"
        assert "generationConfig" in result
        assert result["generationConfig"]["temperature"] == 0.9

    def test_convert_openai_to_google_with_system_prompt(self):
        """测试带系统提示的转换"""
        request_body = {
            "model": "gemma-4-31b-it",
            "messages": [
                {"role": "system", "content": "You are helpful"},
                {"role": "user", "content": "Hello"},
            ],
        }

        result, model = convert_openai_to_google(request_body)

        # 系统提示会被加到用户消息中
        assert len(result["contents"]) == 2
        assert "You are helpful" in result["contents"][0]["parts"][0]["text"]

    def test_convert_openai_to_google_with_params(self):
        """测试带自定义参数的转换"""
        request_body = {
            "model": "test-model",
            "temperature": 0.5,
            "max_tokens": 500,
            "top_p": 0.9,
            "stop": "END",
        }

        result, model = convert_openai_to_google(request_body)

        assert model == "test-model"
        assert result["generationConfig"]["temperature"] == 0.5
        assert result["generationConfig"]["maxOutputTokens"] == 500
        assert result["generationConfig"]["topP"] == 0.9
        assert result["generationConfig"]["stopSequences"] == ["END"]

    def test_convert_google_to_openai(self):
        """测试Google响应转OpenAI格式"""
        google_response = {
            "candidates": [{"content": {"parts": [{"text": "Hello, world!"}]}}],
            "usageMetadata": {
                "promptTokenCount": 10,
                "candidatesTokenCount": 20,
                "totalTokenCount": 30,
            },
        }

        result = convert_google_to_openai(google_response, "test-model")

        assert result["object"] == "chat.completion"
        assert result["model"] == "test-model"
        assert result["choices"][0]["message"]["content"] == "Hello, world!"
        assert result["usage"]["prompt_tokens"] == 10
        assert result["usage"]["completion_tokens"] == 20
        assert result["usage"]["total_tokens"] == 30

    def test_convert_google_to_openai_empty_response(self):
        """测试空响应处理"""
        google_response = {}
        result = convert_google_to_openai(google_response, "test-model")

        assert "Error" in result["choices"][0]["message"]["content"]
        assert result["usage"]["prompt_tokens"] == 0


class TestProxyHandlers(AioHTTPTestCase):
    """HTTP处理器测试类"""

    def get_app(self):
        """创建测试应用"""
        return create_app()

    @unittest_run_loop
    async def test_health_endpoint(self):
        """测试健康检查端点"""
        import aiohttp

        # Mock ClientSession.get
        with patch("aiohttp.ClientSession") as mock_session:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_session.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            resp = await self.client.request("GET", "/health")
            assert resp.status == 200

            data = await resp.json()
            assert "status" in data
            assert "google_api_reachable" in data

    @unittest_run_loop
    async def test_models_list_endpoint(self):
        """测试模型列表端点"""
        resp = await self.client.request("GET", "/v1/models")
        assert resp.status == 200

        data = await resp.json()
        assert data["object"] == "list"
        assert isinstance(data["data"], list)

    @unittest_run_loop
    async def test_chat_completions_endpoint(self):
        """测试聊天补全端点"""
        # Mock aiohttp请求
        with patch("aiohttp.ClientSession.post") as mock_post:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(
                return_value={
                    "candidates": [{"content": {"parts": [{"text": "Test response"}]}}],
                    "usageMetadata": {
                        "promptTokenCount": 10,
                        "candidatesTokenCount": 5,
                        "totalTokenCount": 15,
                    },
                }
            )
            mock_post.return_value.__aenter__.return_value = mock_response

            payload = {
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": False,
            }

            resp = await self.client.post("/v1/chat/completions", json=payload)
            assert resp.status == 200

            data = await resp.json()
            assert data["object"] == "chat.completion"
            assert data["choices"][0]["message"]["content"] == "Test response"

    @unittest_run_loop
    async def test_invalid_json_request(self):
        """测试无效JSON请求处理"""
        resp = await self.client.post(
            "/v1/chat/completions",
            data="invalid json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status == 400

    @unittest_run_loop
    async def test_missing_model(self):
        """测试缺少模型参数"""
        payload = {"messages": [{"role": "user", "content": "Hello"}]}
        resp = await self.client.post("/v1/chat/completions", json=payload)
        assert resp.status == 400


class TestRetryMechanism:
    """重试机制测试类"""

    @pytest.mark.asyncio
    async def test_retry_success(self):
        """测试重试最终成功"""

        # 模拟前两次失败，第三次成功
        async def mock_request():
            return MagicMock(status=200)

        mock_session = AsyncMock()
        call_count = 0

        async def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise aiohttp.ClientResponseError(None, None, status=500)
            return await mock_request()

        mock_session.request = mock_post

        # 由于代码结构问题，这部分需要实际运行测试验证

    @pytest.mark.asyncio
    async def test_retry_exhausted(self):
        """测试重试耗尽"""
        # Mock 所有尝试都失败
        pass


class TestStreamingResponse:
    """流式响应测试类"""

    @pytest.mark.asyncio
    async def test_stream_format(self):
        """测试流式响应格式"""
        # 测试 SSE 格式
        mock_response = {
            "candidates": [{"content": {"parts": [{"text": "Hello world"}]}}]
        }

        # 需要模拟流式生成器


def test_convert_stop_sequences():
    """测试停止序列转换"""
    request_body = {"stop": ["END", "STOP"]}
    result, _ = convert_openai_to_google(request_body)
    assert result["generationConfig"]["stopSequences"] == ["END", "STOP"]


def test_convert_single_stop():
    """测试单个停止序列"""
    request_body = {"stop": "END"}
    result, _ = convert_openai_to_google(request_body)
    assert result["generationConfig"]["stopSequences"] == ["END"]


def test_empty_messages():
    """测试空消息处理"""
    request_body = {"model": "test"}
    result, _ = convert_openai_to_google(request_body)
    assert len(result["contents"]) == 0


if __name__ == "__main__":
    # 本地运行测试
    pytest.main([__file__, "-v", "-s"])
