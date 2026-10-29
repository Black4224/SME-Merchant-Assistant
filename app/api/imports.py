import json

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.database import get_session
from app.errors import Conflict, PayloadTooLarge, Unprocessable
from app.services import importer

router = APIRouter(prefix="/api/import/csv", tags=["import"])


async def _read(file: UploadFile) -> bytes:
    data = await file.read(importer.MAX_FILE_BYTES + 1)
    if len(data) > importer.MAX_FILE_BYTES:
        raise PayloadTooLarge("حجم الملف كبير جداً")
    return data


def _mapping(raw: str | None) -> dict[str, str] | None:
    if not raw or not raw.strip():
        return None
    try:
        m = json.loads(raw)
    except json.JSONDecodeError:
        raise Unprocessable("mapping يجب أن يكون JSON صالحاً", code="bad_mapping") from None
    if not isinstance(m, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in m.items()):
        raise Unprocessable("mapping يجب أن يكون كائناً من نصوص: {field: column}", code="bad_mapping")
    return m


@router.post("/preview")
async def preview(file: UploadFile = File(...), mapping: str | None = Form(None), session: Session = Depends(get_session)):
    """Parse + validate + detect duplicates. Writes NOTHING."""
    analysis = importer.analyze_csv(session, await _read(file), file.filename or "upload.csv", _mapping(mapping))
    return analysis.to_dict()


@router.post("/confirm", status_code=201)
async def confirm(
    file: UploadFile = File(...),
    mapping: str | None = Form(None),
    skip_invalid: bool = Form(False),
    expected_sha256: str | None = Form(None),
    session: Session = Depends(get_session),
):
    """Re-validates the file and commits valid, non-duplicate rows in one transaction."""
    content = await _read(file)
    analysis = importer.analyze_csv(session, content, file.filename or "upload.csv", _mapping(mapping))
    if expected_sha256 and expected_sha256 != analysis.sha256:
        raise Conflict("الملف المرفوع يختلف عن الملف الذي تمت معاينته", code="file_changed")
    result = importer.commit_import(session, analysis, skip_invalid=skip_invalid)
    session.commit()
    return result
