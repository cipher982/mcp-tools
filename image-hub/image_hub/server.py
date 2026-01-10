"""
Image Hub - Lightweight MCP facade for Gemini image generation.

Wraps google-genai Vertex AI for image generation with minimal token overhead.
Images are saved to files and paths returned for easy use in agent workflows.
"""

import base64
import io
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastmcp import FastMCP
from PIL import Image

# Create the hub server
mcp = FastMCP(
    "image-hub",
    instructions="""
    Image generation using Gemini 3 Pro via Vertex AI.

    Tools:
    - generate_image: Create image from prompt, returns file path
    - generate_variants: Create multiple variants in parallel, returns file paths
    - edit_image: Modify existing image file with prompt, returns file path

    Images saved to ~/Pictures/image-hub/ by default.
    Requires GOOGLE_APPLICATION_CREDENTIALS for Vertex AI auth.
    """
)

# Configuration
PROJECT_ID = "zeta-phoenix"
LOCATION = "us-central1"
DEFAULT_MODEL = "gemini-3-pro-image-preview"
OUTPUT_DIR = Path.home() / "Pictures" / "image-hub"

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


def ensure_output_dir() -> Path:
    """Ensure output directory exists and return it."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


def save_image(image_bytes: bytes, prefix: str = "img", project: str | None = None) -> str:
    """Save image bytes to file, return absolute path."""
    output_dir = ensure_output_dir()
    if project:
        output_dir = output_dir / project
        output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    short_id = uuid.uuid4().hex[:6]
    filename = f"{prefix}_{timestamp}_{short_id}.png"
    filepath = output_dir / filename
    filepath.write_bytes(image_bytes)
    return str(filepath)


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


@mcp.tool()
def generate_image(
    prompt: str,
    aspect_ratio: str = "1:1",
    project: str | None = None,
) -> dict:
    """
    Generate an image from a text prompt using Gemini 3 Pro.

    Args:
        prompt: Text description of the image to generate
        aspect_ratio: Image dimensions - "1:1", "16:9", "9:16", "4:3", "3:4", etc.
        project: Optional project name for organizing output (creates subdirectory)

    Returns:
        Dict with "path" (absolute file path to PNG) and metadata
    """
    try:
        image_bytes = generate_single_image(prompt, aspect_ratio)

        if image_bytes is None:
            return {"error": "Failed to generate image", "path": None}

        filepath = save_image(image_bytes, prefix="gen", project=project)
        return {
            "path": filepath,
            "aspect_ratio": aspect_ratio,
            "format": "png",
        }
    except Exception as e:
        return {"error": str(e), "path": None}


@mcp.tool()
def generate_variants(
    prompt: str,
    num_variants: int = 2,
    aspect_ratio: str = "1:1",
    project: str | None = None,
) -> dict:
    """
    Generate multiple image variants in parallel (O(1) time).

    Args:
        prompt: Text description for all variants
        num_variants: Number of variants to generate (1-4)
        aspect_ratio: Image dimensions
        project: Optional project name for organizing output (creates subdirectory)

    Returns:
        Dict with "paths" (list of file paths) and metadata
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

        # Save successful results to files
        paths = []
        for i, img_bytes in enumerate(results):
            if img_bytes is not None:
                filepath = save_image(img_bytes, prefix=f"var{i+1}", project=project)
                paths.append(filepath)

        return {
            "paths": paths,
            "count": len(paths),
            "requested": num_variants,
            "aspect_ratio": aspect_ratio,
            "format": "png",
        }
    except Exception as e:
        return {"error": str(e), "paths": [], "count": 0}


@mcp.tool()
def edit_image(
    prompt: str,
    image_path: str,
    aspect_ratio: str | None = None,
    project: str | None = None,
) -> dict:
    """
    Edit an existing image based on a text prompt.

    Args:
        prompt: Instructions for how to modify the image
        image_path: Path to source image file (PNG/JPEG)
        aspect_ratio: Optional new aspect ratio (keeps original if not specified)
        project: Optional project name for organizing output (creates subdirectory)

    Returns:
        Dict with "path" (file path to result) and metadata
    """
    from google.genai import types

    try:
        client = get_client()

        # Read input image
        image_path = Path(image_path).expanduser()
        if not image_path.exists():
            return {"error": f"Image not found: {image_path}", "path": None}

        image_bytes = image_path.read_bytes()

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

        # Detect mime type
        mime_type = "image/png"
        if image_path.suffix.lower() in (".jpg", ".jpeg"):
            mime_type = "image/jpeg"

        # Build multimodal content
        image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

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
                        filepath = save_image(part.inline_data.data, prefix="edit", project=project)
                        return {
                            "path": filepath,
                            "aspect_ratio": aspect_ratio,
                            "format": "png",
                        }

        return {"error": "No image in response", "path": None}

    except Exception as e:
        return {"error": str(e), "path": None}


def main():
    """Entry point for the image-hub server."""
    mcp.run()


if __name__ == "__main__":
    main()
