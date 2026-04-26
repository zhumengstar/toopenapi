#!/usr/bin/env python3
"""
API Endpoints Integration Tests

Comprehensive integration tests for all API endpoints.
Tests cover successful responses, error handling, and edge cases.
"""

import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from aiohttp import ClientResponse, ClientSession, web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from async_server import (
    convert_google_to_openai,
    convert_openai_to_google,
    create_app,
    model_cache,
)

# ==================== Fixtures ====================


@pytest.fixture
def mock_google_models_response():
    """Mock Google AI models API response"""
    return {
        "models": [
            {
                "name": "models/gemma-4-31b-it",
                "displayName": "Gemma 4 31B",
                "description": "Gemma 4 31B model",
                "publisher": "google",
                "createTime": "2024-01-01T00:00:00Z",
                "version": "1.0",
            },
            {
                "name": "models/gemini-pro",
                "displayName": "Gemini Pro",
                "description": "Gemini Pro model",
                "publisher": "google",
                "createTime": "2024-01-01T00:00:00Z",
                "version": "1.0",
            },
        ]
    }


@pytest.fixture
def mock_google_model_detail_response():
    """Mock Google AI single model detail response"""
    return {
        "name": "models/gemma-4-31b-it",
        "displayName": "Gemma 4 31B",
        "description": "Gemma 4 31B instruction-tuned model",
        "publisher": "google",
        "createTime": "2024-01-01T00:00:00Z",
        "version": "1.0",
        "inputTokenLimit": 8192,
        "outputTokenLimit": 2048,
        "temperature": 0.9,
        "topP": 0.95,
    }


@pytest.fixture
def mock_google_chat_response():
    """Mock Google AI chat completion response"""
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "Hello! I am an AI assistant. How can I help you?"}
                    ]
                }
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 10,
            "candidatesTokenCount": 15,
            "totalTokenCount": 25,
        },
    }


@pytest.fixture
def openai_chat_request():
    """OpenAI format chat request"""
    return {
        "model": "gemma-4-31b-it",
        "messages": [{"role": "user", "content": "Hello, who are you?"}],
        "stream": False,
    }


@pytest.fixture
def openai_chat_request_stream():
    """OpenAI format streaming chat request"""
    return {
        "model": "gemma-4-31b-it",
        "messages": [{"role": "user", "content": "Count to 5"}],
        "stream": True,
    }


# ==================== Test Client ====================


@pytest_asyncio.fixture
async def test_client(aiohttp_client):
    """Create test client for the application"""
    app = create_app()
    client = await aiohttp_client(app)
    return client


# ==================== Test Cases ====================


@pytest.mark.asyncio
async def test_health_endpoint(test_client):
    """Test /health endpoint"""
    client = test_client
    with patch("aiohttp.ClientSession.get", new_callable=AsyncMock) as mock_get:
        # Mock successful Google API response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_get.return_value.__aenter__.return_value = mock_response

        resp = await client.get("/health")
        assert resp.status == 200

        data = await resp.json()
        assert data["status"] in ["healthy", "degraded"]
        assert "timestamp" in data
        assert isinstance(data["google_api_reachable"], bool)


@pytest.mark.asyncio
async def test_health_endpoint_google_api_unreachable(test_client):
    """Test /health endpoint when Google API is unreachable"""
    client = test_client
    with patch("aiohttp.ClientSession.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = Exception("Connection failed")

        resp = await client.get("/health")
        assert resp.status == 200

        data = await resp.json()
        assert data["status"] == "degraded"
        assert data["google_api_reachable"] == False


@pytest.mark.asyncio
async def test_models_list_endpoint(test_client, mock_google_models_response):
    """Test /v1/models endpoint"""
    client = test_client
    with patch("aiohttp.ClientSession.get", new_callable=AsyncMock) as mock_get:
        # Mock response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_google_models_response)
        mock_get.return_value.__aenter__.return_value = mock_response

        resp = await client.get("/v1/models")
        assert resp.status == 200

        data = await resp.json()
        assert "object" in data
        assert data["object"] == "list"
        assert "data" in data
        assert len(data["data"]) == 2
        assert data["data"][0]["id"] == "gemma-4-31b-it"


@pytest.mark.asyncio
async def test_models_list_endpoint_cached(test_client):
    """Test /v1/models endpoint uses cache on second call"""
    client = test_client

    # First call - fetch from API
    with patch("aiohttp.ClientSession.get", new_callable=AsyncMock) as mock_get:
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "models": [
                    {
                        "name": "models/test-model",
                        "displayName": "Test Model",
                        "publisher": "google",
                        "createTime": "2024-01-01T00:00:00Z",
                    }
                ]
            }
        )
        mock_get.return_value.__aenter__.return_value = mock_response

        resp1 = await client.get("/v1/models")
        assert resp1.status == 200

    # Second call - should use cache (no new requests)
    with patch("aiohttp.ClientSession.get", new_callable=AsyncMock) as mock_get:
        resp2 = await client.get("/v1/models")
        assert resp2.status == 200
        # Should not call API again within cache period
        mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_model_detail_endpoint(test_client, mock_google_model_detail_response):
    """Test /v1/models/{model_id} endpoint"""
    client = test_client
    with patch("aiohttp.ClientSession.get", new_callable=AsyncMock) as mock_get:
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_google_model_detail_response)
        mock_get.return_value.__aenter__.return_value = mock_response

        resp = await client.get("/v1/models/gemma-4-31b-it")
        assert resp.status == 200

        data = await resp.json()
        assert data["id"] == "gemma-4-31b-it"
        assert data["context_window"] == 8192
        assert data["max_output_tokens"] == 2048


@pytest.mark.asyncio
async def test_model_detail_endpoint_not_found(test_client):
    """Test /v1/models/{model_id} with non-existent model"""
    client = test_client
    with patch("aiohttp.ClientSession.get", new_callable=AsyncMock) as mock_get:
        mock_response = AsyncMock()
        mock_response.status = 404
        mock_get.return_value.__aenter__.return_value = mock_response

        resp = await client.get("/v1/models/non-existent-model")
        assert resp.status == 404


@pytest.mark.asyncio
async def test_chat_completions_endpoint(
    test_client, openai_chat_request, mock_google_chat_response
):
    """Test /v1/chat/completions endpoint (non-streaming)"""
    client = test_client
    with patch("aiohttp.ClientSession.post", new_callable=AsyncMock) as mock_post:
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_google_chat_response)
        mock_post.return_value.__aenter__.return_value = mock_response

        resp = await client.post("/v1/chat/completions", json=openai_chat_request)
        assert resp.status == 200

        data = await resp.json()
        assert data["object"] == "chat.completion"
        assert "choices" in data
        assert len(data["choices"]) == 1
        assert data["choices"][0]["message"]["role"] == "assistant"
        assert "content" in data["choices"][0]["message"]
        assert data["usage"]["prompt_tokens"] == 10
        assert data["usage"]["completion_tokens"] == 15


@pytest.mark.asyncio
async def test_chat_completions_endpoint_with_api_error(
    test_client, openai_chat_request
):
    """Test /v1/chat/completions endpoint handles API errors"""
    client = test_client
    with patch("aiohttp.ClientSession.post", new_callable=AsyncMock) as mock_post:
        mock_response = AsyncMock()
        mock_response.status = 400
        mock_response.json = AsyncMock(
            return_value={"error": {"message": "Invalid model"}}
        )
        mock_post.return_value.__aenter__.return_value = mock_response

        resp = await client.post("/v1/chat/completions", json=openai_chat_request)
        assert resp.status == 400


@pytest.mark.asyncio
async def test_chat_completions_endpoint_timeout(test_client, openai_chat_request):
    """Test /v1/chat/completions endpoint handles timeout"""
    client = test_client
    with patch("aiohttp.ClientSession.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = asyncio.TimeoutError("Request timeout")

        resp = await client.post("/v1/chat/completions", json=openai_chat_request)
        assert resp.status == 500


@pytest.mark.asyncio
async def test_chat_completions_streaming_endpoint(
    test_client, openai_chat_request_stream, mock_google_chat_response
):
    """Test /v1/chat/completions endpoint (streaming)"""
    client = test_client
    with patch("aiohttp.ClientSession.post", new_callable=AsyncMock) as mock_post:
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_google_chat_response)
        mock_post.return_value.__aenter__.return_value = mock_response

        resp = await client.post(
            "/v1/chat/completions", json=openai_chat_request_stream
        )
        assert resp.status == 200
        assert resp.content_type == "text/event-stream"

        # Read streaming response
        chunks = []
        async for line in resp.content:
            line = line.decode().strip()
            if line.startswith("data: "):
                chunk_data = line[6:]  # Remove "data: " prefix
                if chunk_data != "[DONE]":
                    chunks.append(json.loads(chunk_data))

        assert len(chunks) > 0
        assert all(chunk["object"] == "chat.completion.chunk" for chunk in chunks)


@pytest.mark.asyncio
async def test_chat_completions_invalid_json(test_client):
    """Test /v1/chat/completions with invalid JSON"""
    client = test_client
    resp = await client.post(
        "/v1/chat/completions",
        data="not valid json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_cors_headers(test_client):
    """Test CORS headers are properly set"""
    client = test_client
    resp = await client.options("/v1/chat/completions")
    assert resp.status == 200
    assert "Access-Control-Allow-Origin" in resp.headers
    assert "Access-Control-Allow-Methods" in resp.headers
    assert "Access-Control-Allow-Headers" in resp.headers


@pytest.mark.asyncio
async def test_error_handling_unknown_endpoint(test_client):
    """Test unknown endpoint returns 404"""
    client = test_client
    resp = await client.get("/v1/unknown-endpoint")
    assert resp.status == 404


# ==================== Integration Test Suite ====================


@pytest.mark.asyncio
async def test_complete_workflow(test_client, mock_google_chat_response):
    """Test complete workflow: health -> models -> chat completion"""
    client = test_client

    # Mock all external API calls
    with (
        patch("aiohttp.ClientSession.get", new_callable=AsyncMock) as mock_get,
        patch("aiohttp.ClientSession.post", new_callable=AsyncMock) as mock_post,
    ):
        # Health check
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_get.return_value.__aenter__.return_value = mock_response

        health_resp = await client.get("/health")
        assert health_resp.status == 200

        # Models list
        models_response = AsyncMock()
        models_response.status = 200
        models_response.json = AsyncMock(
            return_value={
                "models": [
                    {
                        "name": "models/gemma-4-31b-it",
                        "displayName": "Gemma",
                        "publisher": "google",
                        "createTime": "2024-01-01T00:00:00Z",
                    }
                ]
            }
        )
        mock_get.return_value.__aenter__.return_value = models_response

        models_resp = await client.get("/v1/models")
        assert models_resp.status == 200

        # Chat completion
        chat_response = AsyncMock()
        chat_response.status = 200
        chat_response.json = AsyncMock(return_value=mock_google_chat_response)
        mock_post.return_value.__aenter__.return_value = chat_response

        chat_resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gemma-4-31b-it",
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": False,
            },
        )
        assert chat_resp.status == 200


# ==================== Benchmark Tests ====================


@pytest.mark.asyncio
async def test_concurrent_requests(test_client):
    """Test handling multiple concurrent requests"""
    client = test_client

    async def make_request():
        return await client.get("/health")

    # Make 10 concurrent requests
    tasks = [make_request() for _ in range(10)]
    responses = await asyncio.gather(*tasks)

    # All should succeed
    assert all(resp.status == 200 for resp in responses)


# ==================== Utility Tests ====================


def test_convert_openai_to_google():
    """Test OpenAI to Google format conversion"""
    openai_request = {
        "model": "test-model",
        "messages": [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ],
        "temperature": 0.8,
        "max_tokens": 100,
    }

    google_request, model = convert_openai_to_google(openai_request)

    assert model == "test-model"
    assert "contents" in google_request
    assert "generationConfig" in google_request
    assert google_request["generationConfig"]["temperature"] == 0.8
    assert google_request["generationConfig"]["maxOutputTokens"] == 100


def test_convert_google_to_openai(mock_google_chat_response):
    """Test Google to OpenAI format conversion"""
    openai_response = convert_google_to_openai(mock_google_chat_response, "test-model")

    assert openai_response["object"] == "chat.completion"
    assert openai_response["model"] == "test-model"
    assert "choices" in openai_response
    assert "usage" in openai_response
    assert openai_response["usage"]["prompt_tokens"] == 10


# ==================== Run Tests ====================


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
