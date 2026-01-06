"""Tests for content extraction functionality."""

import mcp.types
from browser_hub.server import extract_content, extract_text_only


class MockResult:
    def __init__(self, content):
        self.content = content


def test_extract_content_handles_text():
    """Test that extract_content properly extracts TextContent."""
    result = MockResult([mcp.types.TextContent(type="text", text="Hello, world!")])
    blocks = extract_content(result)
    assert blocks == [mcp.types.TextContent(type="text", text="Hello, world!")]


def test_extract_content_handles_multiple_text():
    """Test that extract_content handles multiple TextContent items."""
    result = MockResult(
        [
            mcp.types.TextContent(type="text", text="Line 1"),
            mcp.types.TextContent(type="text", text="Line 2"),
            mcp.types.TextContent(type="text", text="Line 3"),
        ]
    )
    blocks = extract_content(result)
    assert [b.text for b in blocks if b.type == "text"] == ["Line 1", "Line 2", "Line 3"]


def test_extract_content_handles_image():
    """Test that extract_content preserves ImageContent blocks (no data URI conversion)."""
    img = mcp.types.ImageContent(
        type="image",
        mimeType="image/png",
        data="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
    )
    result = MockResult([img])
    blocks = extract_content(result)
    assert blocks == [img]


def test_extract_content_handles_image_with_custom_mime():
    """Test that extract_content uses correct MIME type for images."""
    img = mcp.types.ImageContent(type="image", mimeType="image/jpeg", data="base64data")
    result = MockResult([img])
    blocks = extract_content(result)
    assert blocks == [img]


def test_extract_content_handles_mixed_content():
    """Test that extract_content handles mixed text and image content."""
    t1 = mcp.types.TextContent(type="text", text="Screenshot of page:")
    img = mcp.types.ImageContent(type="image", mimeType="image/png", data="imagedata123")
    t2 = mcp.types.TextContent(type="text", text="Additional info")
    result = MockResult([t1, img, t2])
    blocks = extract_content(result)
    assert blocks == [t1, img, t2]


def test_extract_content_handles_empty_content():
    """Test that extract_content handles empty content list."""
    result = MockResult([])
    blocks = extract_content(result)
    assert blocks == [mcp.types.TextContent(type="text", text="Action completed (no output)")]


def test_extract_content_handles_none_content():
    """Test that extract_content handles None content."""
    class EmptyResult:
        content = None

    result = EmptyResult()
    blocks = extract_content(result)
    assert blocks == [mcp.types.TextContent(type="text", text="Action completed (no output)")]


def test_extract_content_skips_unknown_types():
    """Unknown items are stringified into TextContent."""
    t1 = mcp.types.TextContent(type="text", text="Valid text")
    unknown = object()
    t2 = mcp.types.TextContent(type="text", text="More valid text")
    result = MockResult([t1, unknown, t2])
    blocks = extract_content(result)
    assert blocks[0] == t1
    assert blocks[2] == t2
    assert blocks[1].type == "text"
    assert blocks[1].text  # has some repr


def test_extract_content_handles_malformed_content():
    """Test that extract_content handles content items without type attribute."""
    class MalformedContent:
        # No type attribute
        pass

    t1 = mcp.types.TextContent(type="text", text="Good content")
    result = MockResult([t1, MalformedContent()])
    blocks = extract_content(result)
    assert blocks[0] == t1
    assert blocks[1].type == "text"


def test_extract_content_only_unknown_types():
    """Test behavior when all content items are unknown types."""
    result = MockResult([object(), object()])
    blocks = extract_content(result)
    assert len(blocks) == 2
    assert all(b.type == "text" for b in blocks)


def test_extract_text_only_omits_images():
    img = mcp.types.ImageContent(type="image", mimeType="image/png", data="base64data")
    t1 = mcp.types.TextContent(type="text", text="Hello")
    result = MockResult([t1, img])
    output = extract_text_only(result)
    assert "Hello" in output
    assert "image omitted" in output
