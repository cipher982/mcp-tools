# GDrive Hub

Lightweight MCP facade for Google Drive Shared Drives with service account authentication.

## Features

- **list_files**: List files in folder or search with Drive queries
- **get_file**: Get file metadata
- **upload_file**: Upload local files (uses resumable upload)
- **download_file**: Download files (auto-exports Google Docs to docx/xlsx/pdf)
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

## Query Syntax

The `list_files` tool accepts Google Drive query syntax. Common patterns:

```python
# By name
list_files(query="name = 'exact-name.pdf'")
list_files(query="name contains 'report'")

# By type
list_files(query="mimeType = 'application/pdf'")
list_files(query="mimeType = 'application/vnd.google-apps.folder'")
list_files(query="mimeType = 'application/vnd.google-apps.document'")
list_files(query="mimeType = 'application/vnd.google-apps.spreadsheet'")

# By date
list_files(query="modifiedTime > '2024-01-01'")
list_files(query="createdTime > '2024-01-01T12:00:00'")

# Combine with AND
list_files(query="name contains 'tax' and mimeType = 'application/pdf'")

# Folder + query (searches within folder)
list_files(folder_id="1ABC...", query="name contains 'invoice'")
```

For full query syntax, see [Google Drive API search files](https://developers.google.com/drive/api/guides/search-files).

## Google Docs Export

When downloading Google Docs/Sheets/Slides, they're automatically exported:

| Type | Default Format | Options |
|------|----------------|---------|
| Docs | .docx | pdf, docx, txt |
| Sheets | .xlsx | xlsx, pdf, csv |
| Slides | .pdf | pptx, pdf |

Use the `export_format` parameter to override defaults:

```python
download_file(file_id="1XYZ...", export_format="pdf")
download_file(file_id="1XYZ...", export_format="txt")
```

## Edge Cases

- **Output path**: If `output_path` is omitted, files download to `~/Downloads/`
- **Folder as output**: If `output_path` is a directory, filename is preserved
- **Google Docs**: Cannot be downloaded directly - must be exported (handled automatically)
- **Large files**: Resumable uploads handle large files gracefully
- **Shared Drive root**: With `GDRIVE_DRIVE_ID` set, omitting `folder_id` targets the drive root
