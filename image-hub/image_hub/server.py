"""
Image Hub - Lightweight MCP facade for Gemini image generation.

Wraps google-genai Vertex AI for image generation with minimal token overhead.
Images are saved to files and paths returned for easy use in agent workflows.
"""

import asyncio
import io
import os
import re
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastmcp import FastMCP
from PIL import Image

# Create the hub server
mcp = FastMCP(
    "image-hub",
    instructions="""Image generation via Vertex AI Gemini.

Shared params (all tools): aspect_ratio (1:1|16:9|9:16|4:3|3:4|2:3|3:2|4:5|5:4|21:9),
image_size (1K|2K|4K), person_generation (ALLOW_ALL|ALLOW_ADULT),
output_format (png|jpeg), jpeg_quality (0-100), model (pro|flash), project (subdirectory).
Use batch() for parallel calls.""",
)

# Configuration
PROJECT_ID = "zeta-phoenix"
LOCATION = "global"
MODELS = {
    "pro": "gemini-3-pro-image-preview",
    "flash": "gemini-2.5-flash-image",
}
DEFAULT_MODEL_KEY = "pro"
OUTPUT_DIR = Path.home() / "Pictures" / "image-hub"

# Concurrency limit for Vertex AI calls
_semaphore = asyncio.Semaphore(4)

# Stagger between parallel requests to avoid rate limits (seconds)
STAGGER_DELAY = 1.5

# Valid options
VALID_ASPECT_RATIOS = {
    "1:1", "16:9", "9:16", "4:3", "3:4",
    "2:3", "3:2", "4:5", "5:4", "21:9",
}
VALID_IMAGE_SIZES = {"1K", "2K", "4K"}
VALID_PERSON_GENERATION = {"ALLOW_ALL", "ALLOW_ADULT"}


def _sanitize_project_name(name: str) -> str:
    """Sanitize project name to prevent path traversal attacks."""
    sanitized = re.sub(r"[/\\]", "_", name)
    sanitized = sanitized.replace("..", "_")
    sanitized = re.sub(r"[^A-Za-z0-9_-]", "_", sanitized)
    return sanitized[:64] if sanitized else "default"


def _get_client_sync():
    """Create Vertex AI client (blocking, run in thread)."""
    from google import genai

    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_path:
        local_creds = os.path.join(os.path.dirname(__file__), "google_creds")
        if os.path.exists(local_creds):
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = local_creds

    return genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)


def _get_safety_settings():
    """Return relaxed safety settings."""
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


def _build_image_config(
    aspect_ratio: str = "1:1",
    image_size: str = "1K",
    person_generation: str = "ALLOW_ALL",
    output_format: str = "png",
    jpeg_quality: int = 90,
) -> "types.ImageConfig":
    """Build ImageConfig with all supported parameters."""
    from google.genai import types

    kwargs = {
        "aspect_ratio": aspect_ratio,
    }

    if image_size in VALID_IMAGE_SIZES:
        kwargs["image_size"] = image_size

    if person_generation in VALID_PERSON_GENERATION:
        kwargs["person_generation"] = person_generation

    if output_format == "jpeg":
        kwargs["output_mime_type"] = "image/jpeg"
        kwargs["output_compression_quality"] = max(0, min(100, jpeg_quality))

    return types.ImageConfig(**kwargs)


def _ensure_output_dir(project: str | None = None) -> Path:
    """Ensure output directory exists and return it."""
    output_dir = OUTPUT_DIR
    if project:
        safe_project = _sanitize_project_name(project)
        output_dir = output_dir / safe_project
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _save_image(
    image_bytes: bytes,
    prefix: str = "img",
    project: str | None = None,
    ext: str = "png",
) -> str:
    """Save image bytes to file, return absolute path."""
    output_dir = _ensure_output_dir(project)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    short_id = uuid.uuid4().hex[:6]
    filename = f"{prefix}_{timestamp}_{short_id}.{ext}"
    filepath = output_dir / filename
    filepath.write_bytes(image_bytes)
    return str(filepath)


def _detect_aspect_ratio(image_bytes: bytes) -> str:
    """Detect closest standard aspect ratio from image dimensions."""
    img = Image.open(io.BytesIO(image_bytes))
    w, h = img.size
    ratio = w / h

    # Map ratio ranges to standard aspect ratios
    ratios = [
        (21 / 9, "21:9"),
        (16 / 9, "16:9"),
        (3 / 2, "3:2"),
        (5 / 4, "5:4"),
        (4 / 3, "4:3"),
        (1.0, "1:1"),
        (4 / 5, "4:5"),
        (3 / 4, "3:4"),
        (2 / 3, "2:3"),
        (9 / 16, "9:16"),
    ]

    best = "1:1"
    best_diff = float("inf")
    for target_ratio, name in ratios:
        diff = abs(ratio - target_ratio)
        if diff < best_diff:
            best_diff = diff
            best = name

    return best


def _extract_image_from_response(response) -> tuple[bytes | None, str | None]:
    """Extract image bytes from Gemini response. Returns (bytes, error_message)."""
    if not response.candidates:
        return None, "No candidates in response — prompt may have been blocked by safety filters"

    candidate = response.candidates[0]

    # Check for safety blocks
    if hasattr(candidate, "finish_reason") and candidate.finish_reason:
        reason = str(candidate.finish_reason)
        if "SAFETY" in reason or "BLOCK" in reason:
            return None, f"Image generation blocked by safety filter: {reason}"

    if hasattr(candidate, "content") and candidate.content and candidate.content.parts:
        for part in candidate.content.parts:
            if hasattr(part, "inline_data") and part.inline_data:
                return part.inline_data.data, None

    return None, "No image data in response (model returned text only)"


def _resolve_model(model: str | None) -> str:
    """Resolve model shorthand to full model name."""
    if model is None:
        return MODELS[DEFAULT_MODEL_KEY]
    if model in MODELS:
        return MODELS[model]
    # Assume it's a full model name
    return model


def _generate_single_image_sync(
    client,
    prompt: str,
    aspect_ratio: str = "1:1",
    image_size: str = "1K",
    person_generation: str = "ALLOW_ALL",
    output_format: str = "png",
    jpeg_quality: int = 90,
    model: str | None = None,
) -> tuple[bytes | None, str | None]:
    """Generate a single image synchronously. Returns (bytes, error_message)."""
    from google.genai import types

    resolved_model = _resolve_model(model)
    max_retries = 3
    last_error = None

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=resolved_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    image_config=_build_image_config(
                        aspect_ratio=aspect_ratio,
                        image_size=image_size,
                        person_generation=person_generation,
                        output_format=output_format,
                        jpeg_quality=jpeg_quality,
                    ),
                    safety_settings=_get_safety_settings(),
                ),
            )

            image_bytes, error = _extract_image_from_response(response)
            if image_bytes is not None:
                return image_bytes, None

            last_error = error
            if attempt < max_retries - 1:
                time.sleep(0.5 * (attempt + 1) + (uuid.uuid4().int % 100) / 1000)
                continue

        except Exception as e:
            last_error = str(e)
            if attempt < max_retries - 1:
                time.sleep(0.5 * (attempt + 1) + (uuid.uuid4().int % 100) / 1000)
                continue
            raise

    return None, last_error


@mcp.tool()
async def generate_image(
    prompt: str,
    aspect_ratio: str = "1:1",
    image_size: str = "1K",
    person_generation: str = "ALLOW_ALL",
    output_format: str = "png",
    jpeg_quality: int = 90,
    model: str | None = None,
    project: str | None = None,
) -> dict:
    """Generate an image from a text prompt. Returns {path, aspect_ratio, image_size, format}."""
    async with _semaphore:
        try:
            client = await asyncio.to_thread(_get_client_sync)
            image_bytes, error = await asyncio.to_thread(
                _generate_single_image_sync,
                client,
                prompt,
                aspect_ratio,
                image_size,
                person_generation,
                output_format,
                jpeg_quality,
                model,
            )

            if image_bytes is None:
                return {"error": error or "Failed to generate image", "path": None, "retriable": True}

            ext = "jpg" if output_format == "jpeg" else "png"
            filepath = _save_image(image_bytes, prefix="gen", project=project, ext=ext)
            return {
                "path": filepath,
                "aspect_ratio": aspect_ratio,
                "image_size": image_size,
                "format": output_format,
            }
        except Exception as e:
            retriable = isinstance(e, (OSError, ConnectionError, TimeoutError))
            return {"error": str(e), "path": None, "retriable": retriable}


@mcp.tool()
async def generate_variants(
    prompt: str,
    num_variants: int = 2,
    aspect_ratio: str = "1:1",
    image_size: str = "1K",
    person_generation: str = "ALLOW_ALL",
    output_format: str = "png",
    jpeg_quality: int = 90,
    model: str | None = None,
    project: str | None = None,
) -> dict:
    """Generate num_variants (1-4) images from same prompt in parallel. Returns {paths[], count}."""
    num_variants = min(max(1, num_variants), 4)

    try:
        client = await asyncio.to_thread(_get_client_sync)

        async def gen_one(idx: int):
            # Stagger requests to avoid rate limits
            if idx > 0:
                await asyncio.sleep(STAGGER_DELAY * idx)
            async with _semaphore:
                return await asyncio.to_thread(
                    _generate_single_image_sync,
                    client,
                    prompt,
                    aspect_ratio,
                    image_size,
                    person_generation,
                    output_format,
                    jpeg_quality,
                    model,
                )

        results = await asyncio.gather(*[gen_one(i) for i in range(num_variants)])

        ext = "jpg" if output_format == "jpeg" else "png"
        paths = []
        errors = []
        for i, (img_bytes, error) in enumerate(results):
            if img_bytes is not None:
                filepath = _save_image(img_bytes, prefix=f"var{i + 1}", project=project, ext=ext)
                paths.append(filepath)
            elif error:
                errors.append(f"variant {i + 1}: {error}")

        result = {
            "paths": paths,
            "count": len(paths),
            "requested": num_variants,
            "aspect_ratio": aspect_ratio,
            "image_size": image_size,
            "format": output_format,
        }
        if errors:
            result["errors"] = errors
        return result
    except Exception as e:
        retriable = isinstance(e, (OSError, ConnectionError, TimeoutError))
        return {"error": str(e), "paths": [], "count": 0, "retriable": retriable}


@mcp.tool()
async def edit_image(
    prompt: str,
    image_path: str,
    aspect_ratio: str | None = None,
    image_size: str = "1K",
    person_generation: str = "ALLOW_ALL",
    output_format: str = "png",
    jpeg_quality: int = 90,
    model: str | None = None,
    project: str | None = None,
) -> dict:
    """Edit an existing image based on a text prompt. Aspect ratio auto-detected if not specified. Returns {path}."""
    from google.genai import types

    async with _semaphore:
        try:
            client = await asyncio.to_thread(_get_client_sync)

            image_path_obj = Path(image_path).expanduser()
            if not image_path_obj.exists():
                return {"error": f"Image not found: {image_path_obj}", "path": None, "retriable": False}

            image_bytes = image_path_obj.read_bytes()

            # Auto-detect aspect ratio from source image
            if aspect_ratio is None:
                aspect_ratio = _detect_aspect_ratio(image_bytes)

            # Detect mime type
            mime_type = "image/png"
            if image_path_obj.suffix.lower() in (".jpg", ".jpeg"):
                mime_type = "image/jpeg"

            image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
            resolved_model = _resolve_model(model)

            def _edit():
                max_retries = 3
                last_error = None
                for attempt in range(max_retries):
                    try:
                        response = client.models.generate_content(
                            model=resolved_model,
                            contents=[image_part, prompt],
                            config=types.GenerateContentConfig(
                                image_config=_build_image_config(
                                    aspect_ratio=aspect_ratio,
                                    image_size=image_size,
                                    person_generation=person_generation,
                                    output_format=output_format,
                                    jpeg_quality=jpeg_quality,
                                ),
                                safety_settings=_get_safety_settings(),
                            ),
                        )
                        img_bytes, error = _extract_image_from_response(response)
                        if img_bytes is not None:
                            return img_bytes, None
                        last_error = error
                        if attempt < max_retries - 1:
                            time.sleep(0.5 * (attempt + 1) + (uuid.uuid4().int % 100) / 1000)
                    except Exception as e:
                        last_error = str(e)
                        if attempt < max_retries - 1:
                            time.sleep(0.5 * (attempt + 1) + (uuid.uuid4().int % 100) / 1000)
                            continue
                        raise
                return None, last_error

            img_bytes, error = await asyncio.to_thread(_edit)

            if img_bytes is None:
                return {"error": error or "No image in response", "path": None, "retriable": True}

            ext = "jpg" if output_format == "jpeg" else "png"
            filepath = _save_image(img_bytes, prefix="edit", project=project, ext=ext)
            return {
                "path": filepath,
                "aspect_ratio": aspect_ratio,
                "image_size": image_size,
                "format": output_format,
            }

        except Exception as e:
            retriable = isinstance(e, (OSError, ConnectionError, TimeoutError))
            return {"error": str(e), "path": None, "retriable": retriable}


@mcp.tool()
async def edit_variants(
    prompts: list[str],
    image_path: str,
    aspect_ratio: str | None = None,
    image_size: str = "1K",
    person_generation: str = "ALLOW_ALL",
    output_format: str = "png",
    jpeg_quality: int = 90,
    model: str | None = None,
    project: str | None = None,
) -> dict:
    """Edit one image with multiple different prompts (1-6) in parallel. Returns {paths[], count, errors?}."""
    from google.genai import types

    prompts = prompts[:6]  # Cap at 6
    if not prompts:
        return {"error": "No prompts provided", "paths": [], "count": 0}

    try:
        client = await asyncio.to_thread(_get_client_sync)

        image_path_obj = Path(image_path).expanduser()
        if not image_path_obj.exists():
            return {"error": f"Image not found: {image_path_obj}", "paths": [], "count": 0, "retriable": False}

        image_bytes = image_path_obj.read_bytes()

        if aspect_ratio is None:
            aspect_ratio = _detect_aspect_ratio(image_bytes)

        mime_type = "image/png"
        if image_path_obj.suffix.lower() in (".jpg", ".jpeg"):
            mime_type = "image/jpeg"

        image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        resolved_model = _resolve_model(model)
        config = types.GenerateContentConfig(
            image_config=_build_image_config(
                aspect_ratio=aspect_ratio,
                image_size=image_size,
                person_generation=person_generation,
                output_format=output_format,
                jpeg_quality=jpeg_quality,
            ),
            safety_settings=_get_safety_settings(),
        )

        async def edit_one(idx: int, prompt: str):
            # Stagger to avoid rate limits
            if idx > 0:
                await asyncio.sleep(STAGGER_DELAY * idx)
            async with _semaphore:
                def _do_edit():
                    max_retries = 3
                    last_error = None
                    for attempt in range(max_retries):
                        try:
                            response = client.models.generate_content(
                                model=resolved_model,
                                contents=[image_part, prompt],
                                config=config,
                            )
                            img_bytes, error = _extract_image_from_response(response)
                            if img_bytes is not None:
                                return img_bytes, None
                            last_error = error
                            if attempt < max_retries - 1:
                                time.sleep(0.5 * (attempt + 1) + (uuid.uuid4().int % 100) / 1000)
                        except Exception as e:
                            last_error = str(e)
                            if attempt < max_retries - 1:
                                time.sleep(0.5 * (attempt + 1) + (uuid.uuid4().int % 100) / 1000)
                                continue
                            return None, last_error
                    return None, last_error

                return await asyncio.to_thread(_do_edit)

        results = await asyncio.gather(*[edit_one(i, p) for i, p in enumerate(prompts)])

        ext = "jpg" if output_format == "jpeg" else "png"
        paths = []
        errors = []
        for i, (img_bytes, error) in enumerate(results):
            if img_bytes is not None:
                filepath = _save_image(img_bytes, prefix=f"editv{i + 1}", project=project, ext=ext)
                paths.append(filepath)
            elif error:
                errors.append(f"prompt {i + 1}: {error}")

        result = {
            "paths": paths,
            "count": len(paths),
            "requested": len(prompts),
            "aspect_ratio": aspect_ratio,
            "image_size": image_size,
            "format": output_format,
        }
        if errors:
            result["errors"] = errors
        return result

    except Exception as e:
        retriable = isinstance(e, (OSError, ConnectionError, TimeoutError))
        return {"error": str(e), "paths": [], "count": 0, "retriable": retriable}


# Add batch support for parallel execution
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.batch import add_batch_support

add_batch_support(
    mcp,
    {
        "generate_image": generate_image,
        "generate_variants": generate_variants,
        "edit_image": edit_image,
        "edit_variants": edit_variants,
    },
)


def main():
    """Entry point for the image-hub server."""
    mcp.run()


if __name__ == "__main__":
    main()
