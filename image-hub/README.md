# Image Hub

Lightweight MCP facade for Gemini 3 Pro image generation via Vertex AI.

## Features

- **generate_image**: Create images from text prompts
- **generate_variants**: Create multiple variants in parallel (O(1) time)
- **edit_image**: Modify existing images with prompts

## Configuration

Requires Google Cloud credentials for Vertex AI:

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

Or place a `google_creds` file in the package directory.

## Usage

```bash
cd image-hub && uv sync
uv run image-hub
```
