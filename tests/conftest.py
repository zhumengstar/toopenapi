"""
pytest configuration for async server tests
"""

import asyncio
import os
import sys
from typing import Any, Dict

import aiohttp
import pytest
import pytest_asyncio
from aiohttp import web

# Add parent directory to path to import async_server
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from async_server import create_app


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_client():
    """Create a test client for the async server"""
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "localhost", 0)  # Use random available port
    await site.start()

    # Get the actual port assigned
    port = site._server.sockets[0].getsockname()[1]
    base_url = f"http://localhost:{port}"

    async with aiohttp.ClientSession() as session:
        yield {"session": session, "base_url": base_url, "port": port, "runner": runner}

    # Cleanup
    await runner.cleanup()


@pytest.fixture
def mock_google_response() -> Dict[str, Any]:
    """Mock response from Google AI API"""
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": "Hello! I'm an AI assistant. How can I help you today?"
                        }
                    ]
                }
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 10,
            "candidatesTokenCount": 20,
            "totalTokenCount": 30,
        },
    }


@pytest.fixture
def mock_models_response() -> Dict[str, Any]:
    """Mock response for /models endpoint"""
    return {
        "models": [
            {
                "name": "models/gemma-4-31b-it",
                "publisher": "google",
                "createTime": "2024-01-01T00:00:00Z",
                "description": "Gemma 4 31B IT model",
            },
            {
                "name": "models/gemini-pro",
                "publisher": "google",
                "createTime": "2024-01-01T00:00:00Z",
                "description": "Gemini Pro model",
            },
        ]
    }


@pytest.fixture
def openai_request_payload() -> Dict[str, Any]:
    """Standard OpenAI API request payload"""
    return {
        "model": "gemma-4-31b-it",
        "messages": [{"role": "user", "content": "Hello!"}],
        "max_tokens": 100,
        "temperature": 0.9,
    }


@pytest.fixture
def openai_stream_request() -> Dict[str, Any]:
    """OpenAI API streaming request payload"""
    return {
        "model": "gemma-4-31b-it",
        "messages": [{"role": "user", "content": "Count to 5"}],
        "stream": True,
        "max_tokens": 50,
    }


# pytest configuration
def pytest_configure(config):
    """Configure pytest"""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line("markers", "integration: marks tests as integration tests")


def pytest_addoption(parser):
    """Add custom command line options"""
    parser.addoption(
        "--api-key",
        action="store",
        default=None,
        help="Google API key for integration tests",
    )
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests (requires API key)",
    )


def pytest_collection_modifyitems(config, items):
    """Modify test collection based on command line options"""
    # Skip integration tests if --run-integration is not provided
    if not config.getoption("--run-integration"):
        skip_integration = pytest.mark.skip(
            reason="need --run-integration option to run"
        )
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip_integration)


async def _mock_google_api_response(
    http_client, url, expected_status=200, response_data=None
):
    """Helper to mock Google API responses"""
    from aiohttp import web

    def create_handler(response_data_local):
        async def handler(request):
            return web.json_response(response_data_local, status=expected_status)

        return handler

    app = web.Application()
    app.router.add_routes(
        [
            web.post("/{path:.*}", create_handler(response_data or {"candidates": []})),
            web.get("/{path:.*}", create_handler(response_data or {"models": []})),
        ]
    )

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "localhost", 0)
    await site.start()

    port = site._server.sockets[0].getsockname()[1]

    return f"http://localhost:{port}", runner


@pytest.fixture
async def mock_google_http():
    """Create mock Google HTTP server for testing"""
    from async_test_helpers import _mock_google_api_response

    async def create_mock(response_data=None, status=200):
        return await _mock_google_api_response(None, "mock", status, response_data)

    return create_mock


# Configure async timeouts
@pytest.fixture(autouse=True)
def configure_timeouts():
    """Configure default timeouts for tests"""
    os.environ.setdefault("REQUEST_TIMEOUT", "30")
    os.environ.setdefault("CACHE_DURATION", "5")  # Shorter cache for tests
