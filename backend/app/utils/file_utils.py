import os
import re
import uuid
from pathlib import Path
from app.core.config import settings
from app.core.exceptions import UnsupportedFileTypeError, FileTooLargeError

ALLOWED_EXTENSIONS = {"pdf", "docx", "txt", "xlsx"}


def get_file_type(filename: str) -> str:
    ext = Path(filename).suffix.lstrip(".").lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise UnsupportedFileTypeError(ext)
    return ext


def safe_filename(filename: str) -> str:
    name = Path(filename).stem
    ext  = Path(filename).suffix.lower()
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", name)
    unique = f"{safe}_{uuid.uuid4().hex[:8]}{ext}"
    return unique


def validate_file_size(size_bytes: int):
    if size_bytes > settings.max_file_size_bytes:
        raise FileTooLargeError(settings.MAX_FILE_SIZE_MB)


def get_upload_path(stored_name: str) -> str:
    return os.path.join(settings.UPLOAD_DIR, stored_name)
