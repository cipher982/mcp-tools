# GDrive Hub

Lightweight MCP facade for Google Drive Shared Drives with service account authentication.

## Features

- **list_files**: List files in folder or search with Drive queries
- **get_file**: Get file metadata
- **upload_file**: Upload local files (uses resumable upload)
- **download_file**: Download files (auto-exports Google Docs to txt/csv/pdf)
- **move_file**: Move files between folders
- **create_folder**: Create new folders

## Why This Exists

All existing MCP Google Drive servers use OAuth for personal accounts. This server:
- Uses service account auth via `GOOGLE_APPLICATION_CREDENTIALS`
- Supports Shared Drives (`supportsAllDrives=True`)

## Configuration

Required:
```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

Optional (for Shared Drives):
```bash
export GDRIVE_DRIVE_ID=your-shared-drive-id
```

## Usage

```bash
cd gdrive-hub && uv sync
uv run gdrive-hub
```

## Claude Code Config

```json
{
  "mcpServers": {
    "gdrive-hub": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/path/to/mcp-tools/gdrive-hub", "gdrive-hub"],
      "env": {
        "GOOGLE_APPLICATION_CREDENTIALS": "/path/to/service-account.json",
        "GDRIVE_DRIVE_ID": "your-shared-drive-id"
      }
    }
  }
}
```

## Google Docs Export

When downloading Google Docs/Sheets/Slides, they're automatically exported:

| Type | Default Format | Options |
|------|----------------|---------|
| Docs | .docx | pdf, docx, txt |
| Sheets | .xlsx | xlsx, pdf, csv |
| Slides | .pdf | pptx, pdf |

Use the `export_format` parameter to override defaults.
