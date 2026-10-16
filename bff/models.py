"""Boundary response models derived from v0.8 router/repository; no ATS calculation."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Login(Strict):
    password: str = Field(min_length=1, max_length=1024, repr=False)


class Session(Strict):
    authenticated: bool
    operator_id: str | None = None


class CSRF(Strict):
    csrf_token: str


class ResumeSummary(Strict):
    id: int
    filename: str
    format: Literal["pdf", "docx", "json"]
    status: str
    pages: int | None
    created_at: str


class Resume(ResumeSummary):
    sha256: str
    extracted_text: str
    warnings: list[str]
    profile_revision: int


class Profile(Strict):
    id: int
    resume_id: int
    revision: int
    notes: str
    created_at: str
    profile: dict[str, Any]  # additionally checked against pinned ProfessionalProfile schema


class Evidence(Strict):
    text: str
    source: str
    normalized_span: list[int]


class Requirement(Strict):
    id: str
    type: Literal["mandatory", "desirable", "unspecified"]
    category: str
    term: str
    minimum_years: int | None
    evidence: Evidence
    interpretation: str


class Analysis(Strict):
    id: int
    job_id: int
    job_title: str
    seniority: str
    original_description: str
    requirements: list[Requirement]
    analyzer_version: str


class Match(Strict):
    requirement_id: str
    type: Literal["mandatory", "desirable", "unspecified"]
    state: Literal["matched", "partially_matched", "not_demonstrated", "unknown"]
    evidence_ids: list[str]
    experience_ids: list[str]
    project_ids: list[str]
    evidence: list[str]
    justification: str
    gaps: list[str]


class Matching(Strict):
    job_match_score: int | None
    matches: list[Match]
    matcher_version: str


class Suggestion(Strict):
    id: int
    version_id: int
    section: Literal["summary", "experiences", "skills", "achievements"]
    original: list[str]
    suggested: list[str]
    type: Literal["unchanged", "rewritten", "removed", "reordered", "highlighted"]
    decision: Literal["pending", "accepted", "rejected"]
    justification: str
    evidence_ids: list[str]
    original_content: list[str] | None = None
    suggested_content: list[str] | None = None
    sources: list[dict[str, Any]] | None = None


class Export(Strict):
    id: int
    format: Literal["pdf", "docx"]
    filename: str
    sha256: str
    size: int
    revision: int


class Review(Strict):
    id: int
    version_id: int
    revision: int
    event: dict[str, Any]
    notes: str
    created_at: str


class Plan(Strict):
    summary: list[str]
    experiences: list[str]
    skills: list[str]
    achievements: list[str]


class Version(Strict):
    id: int
    resume_id: int
    job_id: int
    profile_id: int
    analysis_id: int
    version_number: int
    language: Literal["pt-BR", "en"]
    template: Literal["ats-simple-v1"]
    engine: Literal["deterministic", "claude_code", "codex"]
    consent_external: Literal[0, 1]
    state: Literal["draft", "pending_review", "rejected", "approved", "superseded"]
    review_revision: int
    base_plan: Plan
    matching: Matching
    created_at: str
    suggestions: list[Suggestion]
    exports: list[Export]
    reviews: list[Review]


class Check(Strict):
    criterion: str
    passed: bool
    weight: int


class Report(Strict):
    job_match_score: int | None
    resume_match_score: int | None
    ats_readability_score: int
    checks: list[Check]
    repeated_terms: list[str]
    evidence_matching: list[Match]
    language_policy: str
    limitations: list[str]
    rendered_evidence_ids: list[str]
    profile_revision: int
