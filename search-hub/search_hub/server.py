"""
Search Hub - Lightweight MCP facade for web search.

Supports:
- OpenAI (GPT-5.2 + web_search tool) for general research
- xAI (Grok-4-1-fast + x_search tool) for Twitter/X discussions
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
from xai_sdk import AsyncClient as XaiAsyncClient
from xai_sdk.chat import user as xai_user
from xai_sdk.tools import x_search

# Create the hub server
mcp = FastMCP(
    "search-hub",
    instructions="""
    Agentic web research - the model autonomously searches and synthesizes.

    ONE call with a specific question. The model handles multiple searches internally.
    Ask what you actually want to know, not search keywords.

    Sources:
    - "openai" (default): GPT-5.2 with web search for general research
    - "x": Grok with X Search for Twitter/X discussions and trends
    - "both": Run both in parallel, returns separate answers

    PARALLEL CALLS: MCP runs tool calls serially. To run multiple searches
    in parallel, use batch() instead of separate web_research calls.
    Example: batch(calls=[{"tool": "web_research", "args": {"task": "..."}},
                          {"tool": "web_research", "args": {"task": "..."}}])
    """
)

# Initialize clients lazily
_openai_client = None
_xai_client = None


def get_openai_client() -> AsyncOpenAI:
    """Get or create async OpenAI client."""
    global _openai_client
    if _openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")
        _openai_client = AsyncOpenAI(api_key=api_key)
    return _openai_client


def get_xai_client() -> XaiAsyncClient:
    """Get or create async xAI client (native SDK)."""
    global _xai_client
    if _xai_client is None:
        api_key = os.getenv("XAI_API_KEY")
        if not api_key:
            raise ValueError("XAI_API_KEY environment variable not set")
        _xai_client = XaiAsyncClient(api_key=api_key)
    return _xai_client


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


async def _openai_search(task: str, reasoning_effort: str) -> dict:
    """OpenAI web search implementation."""
    client = get_openai_client()

    response = await client.responses.create(
        model="gpt-5.2",
        input=task,
        tools=[{"type": "web_search"}],
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

    return {"answer": answer or "", "sources": sources}


async def _xai_search(task: str) -> dict:
    """xAI X Search implementation for Twitter/X discussions."""
    client = get_xai_client()

    # Create chat with X search tool enabled
    chat = client.chat.create(
        model="grok-4-1-fast",
        tools=[x_search()],
    )

    # Add user message and get response
    chat.append(xai_user(task))
    response = await chat.sample()

    # Extract answer
    answer = response.content if hasattr(response, 'content') else str(response)

    # Extract sources from citations
    sources = []
    if hasattr(response, 'citations') and response.citations:
        for url in response.citations:
            sources.append({"url": url})

    return {"answer": answer, "sources": sources}


@mcp.tool()
async def web_research(
    task: str,
    source: Literal["openai", "x", "both"] = "openai",
    reasoning_effort: Literal["low", "medium", "high"] = "medium",
) -> str:
    """
    Research a topic using agentic web search.
    Pass complete questions or tasks, not keywords.

    Good: "How does xAI's Grok API handle tool calling for X Search?"
    Bad: "xAI API docs" or "Grok tool calling"

    Sources:
    - "openai" (default): GPT-5.2 with web_search tool for general research
    - "x": Grok-4-1-fast with x_search tool for Twitter/X discussions and trends
    - "both": Run both in parallel, returns separate answers

    ONE call is sufficient - the model runs multiple searches internally.
    Returns synthesized answer with source URLs.
    """
    request_id = uuid.uuid4().hex[:6]
    start_time = time.time()
    timeout_seconds = 300  # 5 minute timeout
    print(f"[{request_id}] STARTED source={source} - task: {task[:50]}...", file=sys.stderr, flush=True)

    def _format_error(exc: Exception, provider: str) -> dict:
        """Format an exception as a structured error dict."""
        error_str = str(exc).lower()
        is_timeout = isinstance(exc, asyncio.TimeoutError)
        retriable = is_timeout or isinstance(exc, (OSError, ConnectionError, TimeoutError))
        if "rate" in error_str or "429" in error_str or "timeout" in error_str:
            retriable = True
        error_msg = f"{provider} search timed out after {timeout_seconds}s" if is_timeout else str(exc)
        return {"error": error_msg, "retriable": retriable}

    try:
        if source == "both":
            # Run both searches in parallel with timeout
            openai_task = asyncio.wait_for(
                _openai_search(task, reasoning_effort),
                timeout=timeout_seconds
            )
            x_task = asyncio.wait_for(
                _xai_search(task),
                timeout=timeout_seconds
            )
            openai_result, x_result = await asyncio.gather(openai_task, x_task, return_exceptions=True)

            # Handle potential errors from either with structured error info
            if isinstance(openai_result, dict):
                openai_answer = openai_result.get("answer", "")
                openai_sources = openai_result.get("sources", [])
                openai_error = None
            else:
                openai_error = _format_error(openai_result, "OpenAI")
                openai_answer = openai_error["error"]
                openai_sources = []

            if isinstance(x_result, dict):
                x_answer = x_result.get("answer", "")
                x_sources = x_result.get("sources", [])
                x_error = None
            else:
                x_error = _format_error(x_result, "xAI")
                x_answer = x_error["error"]
                x_sources = []

            result = {
                "openai_answer": openai_answer,
                "x_answer": x_answer,
                "sources": {"openai": openai_sources, "x": x_sources},
                "source": "both",
                "timing": {
                    "request_id": request_id,
                    "duration_sec": time.time() - start_time
                }
            }
            # Add structured errors if any occurred
            if openai_error or x_error:
                result["errors"] = {}
                if openai_error:
                    result["errors"]["openai"] = openai_error
                if x_error:
                    result["errors"]["x"] = x_error
        elif source == "x":
            result_data = await asyncio.wait_for(
                _xai_search(task),
                timeout=timeout_seconds
            )
            result = {
                "answer": result_data["answer"],
                "sources": result_data["sources"],
                "source": source,
                "timing": {
                    "request_id": request_id,
                    "duration_sec": time.time() - start_time
                }
            }
        else:
            result_data = await asyncio.wait_for(
                _openai_search(task, reasoning_effort),
                timeout=timeout_seconds
            )
            result = {
                "answer": result_data["answer"],
                "sources": result_data["sources"],
                "source": source,
                "timing": {
                    "request_id": request_id,
                    "duration_sec": time.time() - start_time
                }
            }

        end_time = time.time()
        print(f"[{request_id}] FINISHED - duration: {end_time - start_time:.2f}s", file=sys.stderr, flush=True)

        return json.dumps(result, indent=2)

    except Exception as e:
        end_time = time.time()
        print(f"[{request_id}] ERROR - duration: {end_time - start_time:.2f}s - {e}", file=sys.stderr, flush=True)

        is_timeout = isinstance(e, asyncio.TimeoutError)
        retriable = is_timeout or isinstance(e, (OSError, ConnectionError, TimeoutError))
        error_str = str(e).lower()
        if "rate" in error_str or "429" in error_str or "timeout" in error_str:
            retriable = True

        error_msg = f"Search timed out after {timeout_seconds}s" if is_timeout else str(e)

        error_result = {
            "error": error_msg,
            "answer": None,
            "sources": [],
            "source": source,
            "retriable": retriable,
            "timing": {
                "request_id": request_id,
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
