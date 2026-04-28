"""
POST /api/parse — extract text from an uploaded file.

Accepts multipart/form-data with a single 'file' field. Returns the extracted
text plus metadata and any non-fatal warnings.

This route is intentionally thin: it validates the upload, calls the parser
service, and translates parser exceptions into HTTP errors. All real logic
lives in app/services/parser.py.
"""

from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.config import get_settings
from app.schemas import ErrorDetail, ParseResponse
from app.services import parser

router = APIRouter()


@router.post(
    "/parse",
    response_model=ParseResponse,
    responses={
        400: {
            "model": ErrorDetail,
            "description": "Unsupported file type, encrypted PDF, or scanned PDF",
        },
        413: {"model": ErrorDetail, "description": "File too large"},
        422: {"model": ErrorDetail, "description": "File could not be parsed (corrupted)"},
    },
)
async def parse_file_endpoint(
    file: Annotated[UploadFile, File(...)],
) -> ParseResponse:
    settings = get_settings()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024

    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorDetail(
                error="missing_filename",
                message="The uploaded file has no filename. We need it to detect the file type.",
            ).model_dump(),
        )

    # Read the body. Starlette's UploadFile handles streaming under the hood;
    # for V1 we accept the buffering cost since files are small (<10MB).
    data = await file.read()

    if len(data) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=ErrorDetail(
                error="file_too_large",
                message=f"File exceeds the {settings.max_upload_size_mb}MB limit.",
                detail=f"Received {len(data) / 1024 / 1024:.1f}MB.",
            ).model_dump(),
        )

    try:
        result = parser.parse_file(data, file.filename)
    except parser.UnsupportedFileType as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorDetail(error=e.code, message=e.message, detail=e.detail).model_dump(),
        ) from e
    except parser.ScannedPDFError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorDetail(error=e.code, message=e.message, detail=e.detail).model_dump(),
        ) from e
    except parser.EncryptedPDFError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorDetail(error=e.code, message=e.message, detail=e.detail).model_dump(),
        ) from e
    except parser.CorruptedFileError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ErrorDetail(error=e.code, message=e.message, detail=e.detail).model_dump(),
        ) from e

    return ParseResponse(
        text=result.text,
        metadata=result.metadata,
        warnings=result.warnings,
    )
