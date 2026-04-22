from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class _CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
        ser_json_bytes="base64",
    )


class Blob(_CamelModel):
    mime_type: str
    data: str


class Part(_CamelModel):
    text: str | None = None
    inline_data: Blob | None = None


class Content(_CamelModel):
    role: str = "model"
    parts: list[Part] = Field(default_factory=list)


class Candidate(_CamelModel):
    content: Content
    finish_reason: str = "STOP"
    index: int = 0


class UsageMetadata(_CamelModel):
    prompt_token_count: int = 0
    candidates_token_count: int = 0
    total_token_count: int = 0


class GenerateContentResponse(_CamelModel):
    candidates: list[Candidate]
    usage_metadata: UsageMetadata = Field(default_factory=UsageMetadata)
    model_version: str | None = None


class ErrorBody(BaseModel):
    code: int
    status: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody
