"""
Image Hub - Lightweight MCP facade for Gemini image generation.

Wraps google-genai Vertex AI for image generation with minimal token overhead.
"""

import base64
import io
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from fastmcp import FastMCP
from PIL import Image

# Create the hub server
mcp = FastMCP(
    "image-hub",
    instructions="""
    Image generation using Gemini 3 Pro via Vertex AI.

    Tools:
    - generate_image: Create images from text prompts
    - generate_variants: Create multiple image variants in parallel
    - edit_image: Modify an existing image with a prompt

    Requires GOOGLE_APPLICATION_CREDENTIALS for Vertex AI auth.
    """
)

# Configuration
PROJECT_ID = "zeta-phoenix"
LOCATION = "us-central1"
DEFAULT_MODEL = "gemini-3-pro-image-preview"

# Valid aspect ratios
ASPECT_RATIOS = Literal[
    "1:1", "2:3", "3:2", "3:4", "4:3",
    "4:5", "5:4", "9:16", "16:9", "21:9"
]

# Global client (lazy init)
_client = None


def get_client():
    """Get or create Vertex AI client."""
    global _client
    if _client is not None:
        return _client

    from google import genai

    # Check for credentials
    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_path:
        # Check for local creds file
        local_creds = os.path.join(os.path.dirname(__file__), "google_creds")
        if os.path.exists(local_creds):
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = local_creds

    _client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
    return _client


def get_safety_settings():
    """Return relaxed safety settings for ad generation."""
    from google.genai import types

    return [
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
            threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
        ),
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
            threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
        ),
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
            threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
        ),
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
            threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
        ),
    ]


def generate_single_image(
    prompt: str,
    aspect_ratio: str = "1:1",
    model: str = DEFAULT_MODEL,
) -> bytes | None:
    """Generate a single image, returning PNG bytes or None on failure."""
    from google.genai import types

    client = get_client()
    max_retries = 2

    for attempt in range(max_retries + 1):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
                    safety_settings=get_safety_settings(),
                ),
            )

            # Extract image from response
            if not response.candidates:
                continue

            candidate = response.candidates[0]
            if hasattr(candidate, 'content') and candidate.content and candidate.content.parts:
                for part in candidate.content.parts:
                    if hasattr(part, "inline_data") and part.inline_data:
                        return part.inline_data.data

        except Exception as e:
            if attempt == max_retries:
                raise
            continue

    return None


def image_to_base64(image_bytes: bytes) -> str:
    """Convert image bytes to base64 string."""
    return base64.b64encode(image_bytes).decode("utf-8")


def base64_to_image(b64_string: str) -> Image.Image:
    """Convert base64 string to PIL Image."""
    image_bytes = base64.b64decode(b64_string)
    return Image.open(io.BytesIO(image_bytes))


@mcp.tool()
def generate_image(
    prompt: str,
    aspect_ratio: str = "1:1",
) -> dict:
    """
    Generate an image from a text prompt using Gemini 3 Pro.

    Args:
        prompt: Text description of the image to generate
        aspect_ratio: Image dimensions - "1:1", "16:9", "9:16", "4:3", "3:4", etc.

    Returns:
        Dict with "image" (base64 PNG) and "aspect_ratio"
    """
    try:
        image_bytes = generate_single_image(prompt, aspect_ratio)

        if image_bytes is None:
            return {"error": "Failed to generate image", "image": None}

        return {
            "image": image_to_base64(image_bytes),
            "aspect_ratio": aspect_ratio,
            "format": "png",
        }
    except Exception as e:
        return {"error": str(e), "image": None}


@mcp.tool()
def generate_variants(
    prompt: str,
    num_variants: int = 2,
    aspect_ratio: str = "1:1",
) -> dict:
    """
    Generate multiple image variants in parallel (O(1) time).

    Args:
        prompt: Text description (same prompt for all variants, or unique per variant)
        num_variants: Number of variants to generate (1-4)
        aspect_ratio: Image dimensions

    Returns:
        Dict with "images" (list of base64 PNGs) and metadata
    """
    num_variants = min(max(1, num_variants), 4)  # Clamp to 1-4

    try:
        # Generate in parallel
        with ThreadPoolExecutor(max_workers=num_variants) as executor:
            futures = [
                executor.submit(generate_single_image, prompt, aspect_ratio)
                for _ in range(num_variants)
            ]
            results = [f.result() for f in futures]

        # Convert successful results to base64
        images = [
            image_to_base64(img) for img in results if img is not None
        ]

        return {
            "images": images,
            "count": len(images),
            "requested": num_variants,
            "aspect_ratio": aspect_ratio,
            "format": "png",
        }
    except Exception as e:
        return {"error": str(e), "images": [], "count": 0}


@mcp.tool()
def edit_image(
    prompt: str,
    image_base64: str,
    aspect_ratio: str | None = None,
) -> dict:
    """
    Edit an existing image based on a text prompt.

    Args:
        prompt: Instructions for how to modify the image
        image_base64: Base64-encoded source image (PNG/JPEG)
        aspect_ratio: Optional new aspect ratio (keeps original if not specified)

    Returns:
        Dict with "image" (base64 PNG) and metadata
    """
    from google.genai import types

    try:
        client = get_client()

        # Decode input image
        image_bytes = base64.b64decode(image_base64)

        # Determine aspect ratio from input if not specified
        if aspect_ratio is None:
            img = Image.open(io.BytesIO(image_bytes))
            w, h = img.size
            # Find closest standard ratio
            ratio = w / h
            if ratio > 1.5:
                aspect_ratio = "16:9"
            elif ratio < 0.67:
                aspect_ratio = "9:16"
            else:
                aspect_ratio = "1:1"

        # Build multimodal content
        image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/png")

        response = client.models.generate_content(
            model=DEFAULT_MODEL,
            contents=[image_part, prompt],
            config=types.GenerateContentConfig(
                image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
                safety_settings=get_safety_settings(),
            ),
        )

        # Extract result image
        if response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, 'content') and candidate.content and candidate.content.parts:
                for part in candidate.content.parts:
                    if hasattr(part, "inline_data") and part.inline_data:
                        return {
                            "image": image_to_base64(part.inline_data.data),
                            "aspect_ratio": aspect_ratio,
                            "format": "png",
                        }

        return {"error": "No image in response", "image": None}

    except Exception as e:
        return {"error": str(e), "image": None}


def main():
    """Entry point for the image-hub server."""
    mcp.run()


if __name__ == "__main__":
    main()
