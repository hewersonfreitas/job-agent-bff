"""Bounded signature/format checks; full parsing stays in the ATS sandbox."""

import io
import json
import re
import zipfile

from fastapi import HTTPException

from bff.contracts import validate_schema

MEDIA = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/json": "json",
}


def filename(value, extension):
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _().-]{0,179}", value)
        or ".." in value
        or not value.lower().endswith("." + extension)
    ):
        raise HTTPException(422, "Invalid upload filename")
    return value


def validate_upload(data, media, name):
    extension = MEDIA.get(media)
    if extension is None:
        raise HTTPException(415, "Unsupported media type")
    try:
        if extension == "json":
            payload = json.loads(data)
            if isinstance(payload, dict) and "profile" in payload:
                validate_schema("JsonImport", payload)
                name = payload.get("filename", "master.json")
            else:
                validate_schema("ProfessionalProfile", payload)
        elif extension == "pdf":
            if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-2048:]:
                raise ValueError()
        else:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                files = archive.infolist()
                if (
                    len(files) > 1000
                    or sum(f.file_size for f in files) > 40 * 1024 * 1024
                    or any(
                        f.flag_bits & 1 or ".." in f.filename or f.filename.startswith("/")
                        for f in files
                    )
                    or not {"[Content_Types].xml", "word/document.xml"} <= set(archive.namelist())
                    or any("vbaproject" in f.filename.lower() for f in files)
                ):
                    raise ValueError()
        return filename(name, extension)
    except HTTPException:
        raise
    except (ValueError, UnicodeError, zipfile.BadZipFile, KeyError):
        raise HTTPException(422, "Invalid upload") from None
