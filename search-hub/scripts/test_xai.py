#!/usr/bin/env python3
"""Test xAI API with X Search tool."""

import asyncio
import json
import os
from openai import AsyncOpenAI

# xAI API key - must be set in environment
XAI_API_KEY = os.getenv("XAI_API_KEY")
if not XAI_API_KEY:
    raise ValueError("XAI_API_KEY environment variable not set")

async def test_basic_chat():
    """Test basic chat completion without tools."""
    print("=== Test 1: Basic Chat ===")
    client = AsyncOpenAI(
        api_key=XAI_API_KEY,
        base_url="https://api.x.ai/v1"
    )

    response = await client.chat.completions.create(
        model="grok-4-1-fast-non-reasoning",
        messages=[{"role": "user", "content": "Say hello in 5 words or less."}],
    )

    print(f"Response: {response.choices[0].message.content}")
    print(f"Model: {response.model}")
    print(f"Usage: {response.usage}")
    print()
    return True


async def test_x_search():
    """Test X Search via live_search tool."""
    print("=== Test 2: Live Search (X + Web) ===")
    client = AsyncOpenAI(
        api_key=XAI_API_KEY,
        base_url="https://api.x.ai/v1"
    )

    # Try search_parameters at request level
    response = await client.chat.completions.create(
        model="grok-4-1-fast-non-reasoning",
        messages=[{
            "role": "user",
            "content": "What are AI developers discussing about Claude Code CLI on Twitter/X in the last week? Summarize the main topics and sentiment."
        }],
        extra_body={
            "search_parameters": {
                "mode": "auto",
                "sources": [
                    {"type": "x"},
                    {"type": "web"},
                ],
            }
        }
    )

    print(f"Response: {response.choices[0].message.content}")
    print(f"Finish reason: {response.choices[0].finish_reason}")

    # Check for tool calls
    if response.choices[0].message.tool_calls:
        print(f"Tool calls: {len(response.choices[0].message.tool_calls)}")
        for tc in response.choices[0].message.tool_calls:
            print(f"  - {tc.function.name}: {tc.function.arguments[:100]}...")

    # Check for citations
    if hasattr(response, 'citations'):
        print(f"Citations: {response.citations}")

    print(f"Usage: {response.usage}")
    print()

    # Dump full response for inspection
    print("Full response object attributes:")
    print([attr for attr in dir(response) if not attr.startswith('_')])
    print()

    return True


async def test_x_only_search():
    """Test X-only search using search_parameters."""
    print("=== Test 3: X-Only Search ===")
    client = AsyncOpenAI(
        api_key=XAI_API_KEY,
        base_url="https://api.x.ai/v1"
    )

    # Filter to X only
    response = await client.chat.completions.create(
        model="grok-4-1-fast-non-reasoning",
        messages=[{
            "role": "user",
            "content": "What are the latest MCP (Model Context Protocol) discussions on X/Twitter? What tools or servers are people building?"
        }],
        extra_body={
            "search_parameters": {
                "mode": "auto",
                "sources": [{"type": "x"}],
            }
        }
    )

    print(f"Response: {response.choices[0].message.content}")
    print()
    return True


async def main():
    print("Testing xAI API...\n")

    try:
        await test_basic_chat()
        await test_x_search()
        await test_x_only_search()
        print("All tests passed!")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
