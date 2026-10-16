"""Finite operation allowlist pinned to the upstream private OpenAPI."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from bff import models

CONTRACT = json.loads((Path(__file__).resolve().parents[1] / "contracts/ats-v0.8.json").read_text())
REGISTRY = Registry().with_resource(
    "urn:ats",
    Resource.from_contents({**CONTRACT, "$schema": "https://json-schema.org/draft/2020-12/schema"}),
)


def validate_schema(name, value):
    schema = {"$ref": f"urn:ats#/components/schemas/{name}"}
    if name == "JsonImport":
        # JsonImport is used manually by the upstream raw-body router and is not
        # emitted as a component. Preserve its actual strict model shape.
        schema = {
            "type": "object",
            "required": ["profile"],
            "additionalProperties": False,
            "properties": {
                "profile": {"$ref": "urn:ats#/components/schemas/ProfessionalProfile"},
                "filename": {"type": "string", "default": "master.json"},
            },
        }
    Draft202012Validator(schema, registry=REGISTRY).validate(value)


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    body: str | None
    response: object

    @property
    def scope(self):
        return CONTRACT["paths"][self.path][self.method.lower()]["x-ats-scope"]

    def match(self, method, path):
        if method != self.method:
            return None
        pattern = re.sub(r"\{\w+\}", r"([1-9][0-9]{0,17})", self.path)
        return re.fullmatch(pattern, path)


OPERATIONS = (
    Operation("POST", "/resumes/import", "upload", models.Resume),
    Operation("GET", "/resumes", None, list[models.ResumeSummary]),
    Operation("GET", "/resumes/{resume_id}", None, models.Resume),
    Operation("GET", "/resumes/{resume_id}/profile", None, models.Profile),
    Operation("PATCH", "/resumes/{resume_id}/profile", "ProfileReview", models.Profile),
    Operation("POST", "/jobs/{job_id}/requirements/analyze", None, models.Analysis),
    Operation("POST", "/jobs/{job_id}/resumes/tailor", "TailorInput", models.Version),
    Operation("GET", "/jobs/{job_id}/resumes", None, list[models.Version]),
    Operation("GET", "/resumes/versions/{version_id}/diff", None, models.Version),
    Operation("PATCH", "/resumes/versions/{version_id}/review", "VersionReview", models.Version),
    Operation("POST", "/resumes/versions/{version_id}/approve", "Approval", models.Version),
    Operation("GET", "/resumes/versions/{version_id}/export", None, bytes),
    Operation("GET", "/resumes/versions/{version_id}/ats-report", None, models.Report),
)
