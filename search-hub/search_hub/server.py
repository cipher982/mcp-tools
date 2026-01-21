"""
Search Hub - Lightweight MCP facade for OpenAI web search.

Reduces openai-websearch-mcp (~5.2k tokens) to <300 tokens.
"""

import asyncio
import json
import os
import sys
import time
import uuid
from typing import Literal
from fastmcp import FastMCP
from openai import AsyncOpenAI

# Create the hub server
mcp = FastMCP(
    "search-hub",
    instructions="""
    Web research using OpenAI with web search.
    Pass complete questions or tasks, not keywords.
    Returns synthesized answers with citations.
    """
)

# Initialize OpenAI async client
_openai_client = None


def get_openai_client() -> AsyncOpenAI:
    """Get or create async OpenAI client."""
    global _openai_client
    if _openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")
        _openai_client = AsyncOpenAI(api_key=api_key)
    return _openai_client


def extract_sources(response) -> list[dict[str, str]]:
    """Extract sources from web_search_call action."""
    sources = []

    if not hasattr(response, 'output') or not response.output:
        return sources

    for output_item in response.output:
        # Look for web_search_call items with action.sources
        if output_item.type == "web_search_call":
            action = getattr(output_item, 'action', None)
            if action and hasattr(action, 'sources') and action.sources:
                for source in action.sources:
                    # Sources have: type (url/api), url, name (optional)
                    url = getattr(source, 'url', None)
                    if url:  # Only include URL sources, not API sources
                        sources.append({"url": url})

    return sources


@mcp.tool()
async def web_research(
    task: str,
    reasoning_effort: Literal["low", "medium", "high"] = "medium",
) -> str:
    """
    Research a topic using web search with GPT-5.2 reasoning.
    Pass complete questions or tasks, not keywords.

    Good: "What are the latest quantum computing breakthroughs in 2025?"
    Bad: "quantum computing news"

    Returns synthesized answer with source URLs.
    """
    # Timing instrumentation
    request_id = uuid.uuid4().hex[:6]
    start_time = time.time()
    print(f"[{request_id}] STARTED at {start_time:.3f} - task: {task[:50]}...", file=sys.stderr, flush=True)

    client = get_openai_client()

    try:
        # Call OpenAI Responses API with web search + reasoning
        response = await client.responses.create(
            model="gpt-5.2",
            input=task,
            tools=[{"type": "web_search_preview"}],
            include=["web_search_call.action.sources"],
            reasoning={"effort": reasoning_effort},
        )

        # Extract answer - output_text is the simplest way
        answer = getattr(response, 'output_text', None)

        # Fallback: extract from message content if output_text not available
        if not answer and hasattr(response, 'output') and response.output:
            for output_item in response.output:
                if output_item.type == "message" and hasattr(output_item, 'content'):
                    for content_item in output_item.content:
                        if hasattr(content_item, 'text') and content_item.text:
                            answer = content_item.text
                            break
                    if answer:
                        break

        # Extract sources from web_search_call
        sources = extract_sources(response)

        # Return structured output
        result = {
            "answer": answer or "",
            "sources": sources,
            "timing": {
                "request_id": request_id,
                "start": start_time,
                "end": time.time(),
                "duration_sec": time.time() - start_time
            }
        }

        end_time = time.time()
        print(f"[{request_id}] FINISHED at {end_time:.3f} - duration: {end_time - start_time:.2f}s", file=sys.stderr, flush=True)

        return json.dumps(result, indent=2)

    except Exception as e:
        end_time = time.time()
        print(f"[{request_id}] ERROR at {end_time:.3f} - duration: {end_time - start_time:.2f}s - {e}", file=sys.stderr, flush=True)

        # Determine if error is retriable
        retriable = isinstance(e, (OSError, ConnectionError, TimeoutError))
        # Also check for rate limit errors from OpenAI
        error_str = str(e).lower()
        if "rate" in error_str or "429" in error_str or "timeout" in error_str:
            retriable = True

        error_result = {
            "error": str(e),
            "answer": None,
            "sources": [],
            "retriable": retriable,
            "timing": {
                "request_id": request_id,
                "start": start_time,
                "end": end_time,
                "duration_sec": end_time - start_time
            }
        }
        return json.dumps(error_result, indent=2)


# Add batch support for parallel execution
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.batch import add_batch_support

add_batch_support(mcp, {
    "web_research": web_research,
})


def main():
    """Entry point for the search-hub server."""
    mcp.run()


if __name__ == "__main__":
    main()
