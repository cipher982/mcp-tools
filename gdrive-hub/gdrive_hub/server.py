"""
GDrive Hub - Lightweight MCP facade for Google Drive Shared Drives.

Wraps Google Drive API v3 with service account authentication.
Designed for Shared Drives with proper supportsAllDrives parameters.
"""

import asyncio
import io
import os
import sys
import time
import uuid
from pathlib import Path

from fastmcp import FastMCP

# Create the hub server
mcp = FastMCP(
    "gdrive-hub",
    instructions="""
    Google Drive Shared Drive access via service account.

    Tools:
    - list_files: List files in folder or search
    - get_file: Get file metadata
    - upload_file: Upload local file to Drive
    - download_file: Download file (exports Google Docs to docx/xlsx/pdf)
    - move_file: Move file between folders
    - create_folder: Create new folder

    Requires GOOGLE_APPLICATION_CREDENTIALS and optionally GDRIVE_DRIVE_ID.
    """
)

# Google Docs export format mapping
EXPORT_FORMATS = {
    'application/vnd.google-apps.document': {
        'default': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'ext': '.docx',
        'options': {
            'pdf': 'application/pdf',
            'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'txt': 'text/plain',
        }
    },
    'application/vnd.google-apps.spreadsheet': {
        'default': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'ext': '.xlsx',
        'options': {
            'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'pdf': 'application/pdf',
            'csv': 'text/csv',
        }
    },
    'application/vnd.google-apps.presentation': {
        'default': 'application/pdf',
        'ext': '.pdf',
        'options': {
            'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            'pdf': 'application/pdf',
        }
    },
}

# Global credentials (lazy init, thread-safe)
# Note: We cache credentials but create service per-call because googleapiclient
# isn't thread-safe. This allows concurrent async tool calls.
_credentials = None
_creds_lock = asyncio.Lock()

# Concurrency limit to avoid overwhelming the API
_semaphore = asyncio.Semaphore(5)


async def get_credentials():
    """Get or create cached credentials (thread-safe)."""
    global _credentials
    if _credentials is not None:
        return _credentials

    async with _creds_lock:
        # Double-check after acquiring lock
        if _credentials is not None:
            return _credentials

        from google.oauth2 import service_account

        creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if not creds_path:
            raise ValueError("GOOGLE_APPLICATION_CREDENTIALS not set")
        if not os.path.exists(creds_path):
            raise ValueError(f"Credentials file not found: {creds_path}")

        _credentials = service_account.Credentials.from_service_account_file(
            creds_path,
            scopes=['https://www.googleapis.com/auth/drive']
        )
        return _credentials


def _build_service_sync(creds):
    """Build a new Drive service instance (blocking, run in thread)."""
    from googleapiclient.discovery import build

    # Retry loop for transient network errors during MCP startup
    max_retries = 3
    for attempt in range(max_retries):
        try:
            return build('drive', 'v3', credentials=creds)
        except OSError as e:
            if attempt < max_retries - 1 and e.errno in (49, 99):  # 49=macOS, 99=Linux
                time.sleep(0.5 * (attempt + 1))
                continue
            raise
    return None


async def get_service():
    """Get a new Drive service instance for this call (thread-safe)."""
    creds = await get_credentials()
    return await asyncio.to_thread(_build_service_sync, creds)


def get_drive_id() -> str | None:
    """Get configured Shared Drive ID from environment."""
    return os.environ.get("GDRIVE_DRIVE_ID")


def handle_drive_error(e) -> dict:
    """Convert HttpError to structured JSON response with retriable flag."""
    from googleapiclient.errors import HttpError
    if not isinstance(e, HttpError):
        # OSError, network issues are typically retriable
        retriable = isinstance(e, (OSError, ConnectionError, TimeoutError))
        return {"error": str(e), "retriable": retriable}

    status = e.resp.status
    # 429 (rate limit), 5xx (server errors) are retriable
    retriable = status == 429 or status >= 500

    if status == 403:
        return {"error": "Permission denied. Check service account has access to this file/folder.", "retriable": False}
    elif status == 404:
        return {"error": "File or folder not found.", "retriable": False}
    elif status == 400:
        return {"error": f"Bad request: {e.reason}", "retriable": False}
    elif status == 429:
        return {"error": "Rate limited. Try again later.", "retriable": True}
    else:
        return {"error": f"Drive API error ({status}): {e.reason}", "retriable": retriable}


@mcp.tool()
async def list_files(
    folder_id: str | None = None,
    query: str | None = None,
    max_results: int = 50,
) -> dict:
    """
    List files in Shared Drive folder.

    Args:
        folder_id: Folder ID to list (None = Shared Drive root). Can combine with query.
        query: Drive query syntax, e.g. "name contains 'tax'" or "mimeType = 'application/pdf'"
        max_results: Maximum files to return (default 50)

    Returns:
        {files: [{id, name, mimeType, size, webViewLink}], next_page_token?}
    """
    # Timing instrumentation
    request_id = uuid.uuid4().hex[:6]
    start_time = time.time()
    print(f"[gdrive:{request_id}] STARTED at {start_time:.3f}", file=sys.stderr, flush=True)

    from googleapiclient.errors import HttpError

    async with _semaphore:
        try:
            service = await get_service()
            drive_id = get_drive_id()

            # Build query
            q_parts = []
            if folder_id:
                q_parts.append(f"'{folder_id}' in parents")
            elif drive_id:
                q_parts.append(f"'{drive_id}' in parents")

            if query:
                q_parts.append(query)

            # Always exclude trashed
            q_parts.append("trashed = false")

            q = " and ".join(q_parts) if q_parts else None

            # Build request params
            params = {
                "pageSize": min(max_results, 1000),
                "fields": "nextPageToken, files(id, name, mimeType, size, webViewLink)",
                "supportsAllDrives": True,
            }

            # includeItemsFromAllDrives must be True when driveId is specified
            params["includeItemsFromAllDrives"] = True

            if drive_id:
                params["driveId"] = drive_id
                params["corpora"] = "drive"

            if q:
                params["q"] = q

            result = await asyncio.to_thread(
                lambda: service.files().list(**params).execute()
            )

            files = result.get("files", [])
            # Convert size from string to int
            for f in files:
                if "size" in f:
                    f["size"] = int(f["size"])

            response = {"files": files}
            if "nextPageToken" in result:
                response["next_page_token"] = result["nextPageToken"]

            end_time = time.time()
            response["timing"] = {
                "request_id": request_id,
                "start": start_time,
                "end": end_time,
                "duration_sec": end_time - start_time
            }
            print(f"[gdrive:{request_id}] FINISHED at {end_time:.3f} - duration: {end_time - start_time:.2f}s", file=sys.stderr, flush=True)

            return response

        except HttpError as e:
            end_time = time.time()
            print(f"[gdrive:{request_id}] ERROR at {end_time:.3f} - duration: {end_time - start_time:.2f}s", file=sys.stderr, flush=True)
            err = handle_drive_error(e)
            err["timing"] = {"request_id": request_id, "start": start_time, "end": end_time, "duration_sec": end_time - start_time}
            return err
        except Exception as e:
            end_time = time.time()
            print(f"[gdrive:{request_id}] ERROR at {end_time:.3f} - duration: {end_time - start_time:.2f}s", file=sys.stderr, flush=True)
            return {"error": str(e), "retriable": False, "timing": {"request_id": request_id, "start": start_time, "end": end_time, "duration_sec": end_time - start_time}}


@mcp.tool()
async def get_file(file_id: str) -> dict:
    """
    Get file metadata.

    Args:
        file_id: The file ID

    Returns:
        {id, name, mimeType, size, parents, webViewLink, createdTime, modifiedTime}
    """
    from googleapiclient.errors import HttpError

    async with _semaphore:
        try:
            service = await get_service()

            result = await asyncio.to_thread(
                lambda: service.files().get(
                    fileId=file_id,
                    fields="id, name, mimeType, size, parents, webViewLink, createdTime, modifiedTime",
                    supportsAllDrives=True,
                ).execute()
            )

            if "size" in result:
                result["size"] = int(result["size"])

            return result

        except HttpError as e:
            return handle_drive_error(e)
        except Exception as e:
            return {"error": str(e), "retriable": False}


@mcp.tool()
async def upload_file(
    local_path: str,
    folder_id: str | None = None,
    name: str | None = None,
) -> dict:
    """
    Upload file to Shared Drive.

    Args:
        local_path: Path to local file
        folder_id: Destination folder ID (None = Shared Drive root)
        name: Optional filename (defaults to local filename)

    Returns:
        {id, name, webViewLink}
    """
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    async with _semaphore:
        try:
            service = await get_service()
            drive_id = get_drive_id()

            local_path_obj = Path(local_path).expanduser()
            if not local_path_obj.exists():
                return {"error": f"File not found: {local_path_obj}", "retriable": False}

            file_name = name or local_path_obj.name

            # Build metadata
            file_metadata = {"name": file_name}

            if folder_id:
                file_metadata["parents"] = [folder_id]
            elif drive_id:
                file_metadata["parents"] = [drive_id]

            def _upload():
                media = MediaFileUpload(str(local_path_obj), resumable=True)
                return service.files().create(
                    body=file_metadata,
                    media_body=media,
                    fields="id, name, webViewLink",
                    supportsAllDrives=True,
                ).execute()

            result = await asyncio.to_thread(_upload)
            return result

        except HttpError as e:
            return handle_drive_error(e)
        except Exception as e:
            return {"error": str(e), "retriable": False}


@mcp.tool()
async def download_file(
    file_id: str,
    output_path: str | None = None,
    export_format: str | None = None,
) -> dict:
    """
    Download file from Shared Drive.

    Args:
        file_id: The file ID to download
        output_path: Local path to save (None = ~/Downloads/{filename})
        export_format: For Google Docs: pdf, txt, docx, csv, xlsx

    Returns:
        {path, size}
    """
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaIoBaseDownload

    async with _semaphore:
        try:
            service = await get_service()

            # Get file metadata first
            meta = await asyncio.to_thread(
                lambda: service.files().get(
                    fileId=file_id,
                    fields="name, mimeType",
                    supportsAllDrives=True,
                ).execute()
            )

            file_name = meta["name"]
            mime_type = meta["mimeType"]

            # Check if Google Apps file (needs export)
            is_google_doc = mime_type.startswith("application/vnd.google-apps.")

            if is_google_doc:
                export_info = EXPORT_FORMATS.get(mime_type)
                if not export_info:
                    return {"error": f"Cannot export Google type: {mime_type}", "retriable": False}

                # Determine export mime type
                if export_format:
                    if export_format not in export_info["options"]:
                        return {
                            "error": f"Invalid export_format '{export_format}'. "
                                     f"Allowed: {', '.join(sorted(export_info['options']))}",
                            "retriable": False
                        }
                    export_mime = export_info["options"][export_format]
                    ext = f".{export_format}"
                else:
                    export_mime = export_info["default"]
                    ext = export_info["ext"]

                # Export the file
                request = service.files().export_media(
                    fileId=file_id,
                    mimeType=export_mime,
                )

                # Adjust filename
                if not file_name.endswith(ext):
                    file_name = f"{file_name}{ext}"
            else:
                # Regular file download
                request = service.files().get_media(
                    fileId=file_id,
                    supportsAllDrives=True,
                )

            # Determine output path
            if output_path:
                out_path = Path(output_path).expanduser()
                if out_path.is_dir():
                    out_path = out_path / file_name
            else:
                out_path = Path.home() / "Downloads" / file_name

            # Ensure parent directory exists
            out_path.parent.mkdir(parents=True, exist_ok=True)

            def _download():
                with io.FileIO(str(out_path), "wb") as fh:
                    downloader = MediaIoBaseDownload(fh, request)
                    done = False
                    while not done:
                        _, done = downloader.next_chunk()

            await asyncio.to_thread(_download)

            return {
                "path": str(out_path),
                "size": out_path.stat().st_size,
            }

        except HttpError as e:
            return handle_drive_error(e)
        except Exception as e:
            return {"error": str(e), "retriable": False}


@mcp.tool()
async def move_file(file_id: str, dest_folder_id: str) -> dict:
    """
    Move file to different folder.

    Args:
        file_id: The file ID to move
        dest_folder_id: Destination folder ID

    Returns:
        {id, name, parents}
    """
    from googleapiclient.errors import HttpError

    async with _semaphore:
        try:
            service = await get_service()

            # Get current parents
            file_meta = await asyncio.to_thread(
                lambda: service.files().get(
                    fileId=file_id,
                    fields="parents",
                    supportsAllDrives=True,
                ).execute()
            )

            current_parents = ",".join(file_meta.get("parents", []))

            # Move file
            update_kwargs = {
                "fileId": file_id,
                "addParents": dest_folder_id,
                "fields": "id, name, parents",
                "supportsAllDrives": True,
            }
            if current_parents:
                update_kwargs["removeParents"] = current_parents

            result = await asyncio.to_thread(
                lambda: service.files().update(**update_kwargs).execute()
            )

            return result

        except HttpError as e:
            return handle_drive_error(e)
        except Exception as e:
            return {"error": str(e), "retriable": False}


@mcp.tool()
async def create_folder(name: str, parent_id: str | None = None) -> dict:
    """
    Create folder in Shared Drive.

    Args:
        name: Folder name
        parent_id: Parent folder ID (None = Shared Drive root)

    Returns:
        {id, name, webViewLink}
    """
    from googleapiclient.errors import HttpError

    async with _semaphore:
        try:
            service = await get_service()
            drive_id = get_drive_id()

            file_metadata = {
                "name": name,
                "mimeType": "application/vnd.google-apps.folder",
            }

            if parent_id:
                file_metadata["parents"] = [parent_id]
            elif drive_id:
                file_metadata["parents"] = [drive_id]

            result = await asyncio.to_thread(
                lambda: service.files().create(
                    body=file_metadata,
                    fields="id, name, webViewLink",
                    supportsAllDrives=True,
                ).execute()
            )

            return result

        except HttpError as e:
            return handle_drive_error(e)
        except Exception as e:
            return {"error": str(e), "retriable": False}


# Add batch support for parallel execution
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.batch import add_batch_support

add_batch_support(mcp, {
    "list_files": list_files,
    "get_file": get_file,
    "upload_file": upload_file,
    "download_file": download_file,
    "move_file": move_file,
    "create_folder": create_folder,
})


def main():
    """Entry point for the gdrive-hub server."""
    mcp.run()


if __name__ == "__main__":
    main()
