"""Tests for content extraction functionality."""
import pytest
from browser_hub.server import extract_content


class MockTextContent:
    """Mock MCP TextContent."""
    def __init__(self, text: str):
        self.type = "text"
        self.text = text


class MockImageContent:
    """Mock MCP ImageContent."""
    def __init__(self, data: str, mime_type: str = "image/png"):
        self.type = "image"
        self.data = data
        self.mimeType = mime_type


class MockResult:
    """Mock MCP CallToolResult."""
    def __init__(self, content: list):
        self.content = content


def test_extract_content_handles_text():
    """Test that extract_content properly extracts TextContent."""
    result = MockResult([
        MockTextContent("Hello, world!"),
    ])

    output = extract_content(result)
    assert output == "Hello, world!"


def test_extract_content_handles_multiple_text():
    """Test that extract_content handles multiple TextContent items."""
    result = MockResult([
        MockTextContent("Line 1"),
        MockTextContent("Line 2"),
        MockTextContent("Line 3"),
    ])

    output = extract_content(result)
    assert output == "Line 1\nLine 2\nLine 3"


def test_extract_content_handles_image():
    """Test that extract_content properly handles ImageContent."""
    result = MockResult([
        MockImageContent("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="),
    ])

    output = extract_content(result)
    assert output.startswith("data:image/png;base64,")
    assert "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==" in output


def test_extract_content_handles_image_with_custom_mime():
    """Test that extract_content uses correct MIME type for images."""
    result = MockResult([
        MockImageContent("base64data", "image/jpeg"),
    ])

    output = extract_content(result)
    assert output == "data:image/jpeg;base64,base64data"


def test_extract_content_handles_mixed_content():
    """Test that extract_content handles mixed text and image content."""
    result = MockResult([
        MockTextContent("Screenshot of page:"),
        MockImageContent("imagedata123", "image/png"),
        MockTextContent("Additional info"),
    ])

    output = extract_content(result)
    lines = output.split("\n")
    assert len(lines) == 3
    assert lines[0] == "Screenshot of page:"
    assert lines[1] == "data:image/png;base64,imagedata123"
    assert lines[2] == "Additional info"


def test_extract_content_handles_empty_content():
    """Test that extract_content handles empty content list."""
    result = MockResult([])

    output = extract_content(result)
    assert output == "Action completed (no output)"


def test_extract_content_handles_none_content():
    """Test that extract_content handles None content."""
    class EmptyResult:
        content = None

    result = EmptyResult()
    output = extract_content(result)
    assert output == "Action completed (no output)"


def test_extract_content_skips_unknown_types():
    """Test that extract_content gracefully skips unknown content types."""
    class UnknownContent:
        type = "unknown"
        data = "something"

    result = MockResult([
        MockTextContent("Valid text"),
        UnknownContent(),
        MockTextContent("More valid text"),
    ])

    output = extract_content(result)
    # Unknown type should be skipped, only text remains
    assert output == "Valid text\nMore valid text"


def test_extract_content_handles_malformed_content():
    """Test that extract_content handles content items without type attribute."""
    class MalformedContent:
        # No type attribute
        pass

    result = MockResult([
        MockTextContent("Good content"),
        MalformedContent(),
    ])

    output = extract_content(result)
    # Should only extract the good content
    assert output == "Good content"


def test_extract_content_only_unknown_types():
    """Test behavior when all content items are unknown types."""
    class UnknownContent:
        type = "unknown"

    result = MockResult([
        UnknownContent(),
        UnknownContent(),
    ])

    output = extract_content(result)
    # Should return no output message when no valid content
    assert output == "Action completed (no output)"
