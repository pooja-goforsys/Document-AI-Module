from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class NotFoundError(AppError):
    def __init__(self, resource: str = "Resource"):
        super().__init__(f"{resource} not found.", 404)


class UnsupportedFileTypeError(AppError):
    def __init__(self, ext: str):
        super().__init__(f"File type '{ext}' is not supported. Allowed: PDF, DOCX, TXT, XLSX.", 415)


class FileTooLargeError(AppError):
    def __init__(self, max_mb: int):
        super().__init__(f"File exceeds maximum size of {max_mb} MB.", 413)


class IndexingError(AppError):
    def __init__(self, detail: str):
        super().__init__(f"Document indexing failed: {detail}", 500)


class NoRelevantContentError(AppError):
    def __init__(self):
        super().__init__("No relevant information found in the uploaded documents.", 422)


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "message": exc.message},
    )
