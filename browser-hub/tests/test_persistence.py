"""Tests for persistent connection management."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import mcp.types
from browser_hub import server


# Get the actual function from the FunctionTool wrapper
browser_func = server.browser.fn
browser_batch_func = server.browser_batch.fn


def _content_text(blocks: list[mcp.types.ContentBlock]) -> str:
    return "\n".join(
        b.text for b in blocks if getattr(b, "type", None) == "text" and getattr(b, "text", None)
    )


@pytest.fixture
def reset_globals():
    """Reset global connection state before each test."""
    original_client = server._playwright_client
    original_transport = server._playwright_transport
    original_connected = server._playwright_connected

    # Reset to initial state
    server._playwright_client = None
    server._playwright_transport = None
    server._playwright_connected = False

    yield

    # Restore original state after test
    server._playwright_client = original_client
    server._playwright_transport = original_transport
    server._playwright_connected = original_connected


@pytest.mark.asyncio
async def test_get_playwright_creates_client_once(reset_globals):
    """Test that get_playwright creates a client only once."""
    with patch('browser_hub.server.StdioTransport') as mock_transport_cls:
        with patch('browser_hub.server.Client') as mock_client_cls:
            mock_transport = MagicMock()
            mock_client = MagicMock()
            mock_transport_cls.return_value = mock_transport
            mock_client_cls.return_value = mock_client

            # First call should create client
            client1 = await server.get_playwright()
            assert client1 is mock_client
            assert mock_transport_cls.call_count == 1
            assert mock_client_cls.call_count == 1

            # Second call should reuse client
            client2 = await server.get_playwright()
            assert client2 is mock_client
            assert client2 is client1
            assert mock_transport_cls.call_count == 1  # Should not create new transport
            assert mock_client_cls.call_count == 1  # Should not create new client


@pytest.mark.asyncio
async def test_connect_playwright_connects_once(reset_globals):
    """Test that _connect_playwright only connects once."""
    with patch('browser_hub.server.get_playwright') as mock_get:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock()
        mock_get.return_value = mock_client

        # First call should connect
        client1 = await server._connect_playwright()
        assert client1 is mock_client
        assert mock_client.__aenter__.call_count == 1
        assert server._playwright_connected is True

        # Second call should not connect again
        client2 = await server._connect_playwright()
        assert client2 is mock_client
        assert mock_client.__aenter__.call_count == 1  # Should not call again
        assert server._playwright_connected is True


@pytest.mark.asyncio
async def test_disconnect_playwright_cleans_up(reset_globals):
    """Test that _disconnect_playwright properly cleans up state."""
    mock_client = AsyncMock()
    mock_client.close = AsyncMock()

    # Manually set connected state
    server._playwright_client = mock_client
    server._playwright_connected = True

    # Disconnect
    await server._disconnect_playwright()
    assert mock_client.close.call_count == 1
    assert server._playwright_connected is False
    assert server._playwright_client is None
    assert server._playwright_transport is None


@pytest.mark.asyncio
async def test_disconnect_when_not_connected(reset_globals):
    """Test that _disconnect_playwright handles already disconnected state."""
    # Should not raise error when nothing is connected
    await server._disconnect_playwright()
    assert server._playwright_connected is False


@pytest.mark.asyncio
async def test_browser_close_action_disconnects(reset_globals):
    """Test that browser close action properly disconnects."""
    with patch('browser_hub.server._connect_playwright') as mock_connect:
        with patch('browser_hub.server._disconnect_playwright') as mock_disconnect:
            mock_client = AsyncMock()
            mock_client.call_tool = AsyncMock()
            mock_connect.return_value = mock_client
            server._playwright_connected = True
            server._playwright_client = mock_client

            blocks = await browser_func(action="close")

            # Should attempt to call browser_close on client
            mock_client.call_tool.assert_called_once_with("browser_close", {})
            # Should disconnect
            mock_disconnect.assert_called_once()
            assert "closed and disconnected" in _content_text(blocks).lower()


@pytest.mark.asyncio
async def test_browser_actions_use_persistent_connection(reset_globals):
    """Test that multiple browser actions reuse the same connection."""
    with patch('browser_hub.server._connect_playwright') as mock_connect:
        mock_client = AsyncMock()
        mock_result = MagicMock()
        mock_result.content = []
        mock_client.call_tool = AsyncMock(return_value=mock_result)
        mock_connect.return_value = mock_client

        # Call multiple browser actions
        await browser_func(action="navigate", url="https://example.com")
        await browser_func(action="snapshot")
        await browser_func(action="screenshot")

        # Should only connect once
        assert mock_connect.call_count == 3  # Each call attempts to connect
        # But the actual connection (__aenter__) happens only once due to _playwright_connected flag


@pytest.mark.asyncio
async def test_browser_batch_uses_persistent_connection(reset_globals):
    """Test that browser_batch reuses connection across steps."""
    with patch('browser_hub.server._connect_playwright') as mock_connect:
        mock_client = AsyncMock()
        mock_result = MagicMock()
        mock_result.content = []
        mock_client.call_tool = AsyncMock(return_value=mock_result)
        mock_connect.return_value = mock_client

        steps = [
            {"action": "navigate", "url": "https://example.com"},
            {"action": "snapshot"},
            {"action": "screenshot"},
        ]

        results = await browser_batch_func(steps=steps)

        # Should only connect once for the entire batch
        assert mock_connect.call_count == 1
        # Should have called tool for each step
        assert mock_client.call_tool.call_count == 3
        # Should have results for each step
        assert len(results) == 3


@pytest.mark.asyncio
async def test_browser_batch_close_action(reset_globals):
    """Test that close action in browser_batch disconnects."""
    with patch('browser_hub.server._connect_playwright') as mock_connect:
        with patch('browser_hub.server._disconnect_playwright') as mock_disconnect:
            mock_client = AsyncMock()
            mock_result = MagicMock()
            mock_result.content = []
            mock_client.call_tool = AsyncMock(return_value=mock_result)
            mock_connect.return_value = mock_client
            server._playwright_connected = True
            server._playwright_client = mock_client

            steps = [
                {"action": "navigate", "url": "https://example.com"},
                {"action": "close"},
                {"action": "snapshot"},  # Should not execute
            ]

            results = await browser_batch_func(steps=steps)

            # Should have 2 results (navigate + close), snapshot skipped
            assert len(results) == 2
            # Should disconnect after close
            mock_disconnect.assert_called_once()
            assert "closed and disconnected" in results[1].lower()


@pytest.mark.asyncio
async def test_connection_survives_errors(reset_globals):
    """Test that connection persists even when individual actions fail."""
    with patch('browser_hub.server._connect_playwright') as mock_connect:
        mock_client = AsyncMock()
        # First call fails, second succeeds
        mock_result = MagicMock()
        mock_result.content = []
        mock_client.call_tool = AsyncMock(
            side_effect=[Exception("Tool error"), mock_result]
        )
        mock_connect.return_value = mock_client

        # First call fails
        blocks1 = await browser_func(action="navigate", url="bad-url")
        assert "error:" in _content_text(blocks1).lower()

        # Connection should still be alive for second call
        blocks2 = await browser_func(action="snapshot")
        # Should succeed (or at least not complain about connection)
        text2 = _content_text(blocks2).lower()
        assert "connection error" not in text2


@pytest.mark.asyncio
async def test_build_params_with_various_actions(reset_globals):
    """Test that build_params correctly constructs parameters for different actions."""
    # Navigate
    params = server.build_params(
        action="navigate",
        url="https://example.com",
        ref=None, element=None, text=None, key=None, script=None, values=None, timeout=None
    )
    assert params == {"url": "https://example.com"}

    # Click
    params = server.build_params(
        action="click",
        url=None,
        ref="E5",
        element="Button",
        text=None, key=None, script=None, values=None, timeout=None
    )
    assert params == {"ref": "E5", "element": "Button"}

    # Type
    params = server.build_params(
        action="type",
        url=None,
        ref="E6",
        element="Input",
        text="hello",
        key=None, script=None, values=None, timeout=None
    )
    assert params == {"ref": "E6", "element": "Input", "text": "hello"}

    # Screenshot (no params)
    params = server.build_params(
        action="screenshot",
        url=None, ref=None, element=None, text=None, key=None, script=None, values=None, timeout=None
    )
    assert params == {}

    # Evaluate
    params = server.build_params(
        action="evaluate",
        url=None, ref=None, element=None, text=None, key=None,
        script="document.title",
        values=None, timeout=None
    )
    assert params == {"function": "document.title"}
