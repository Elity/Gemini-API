from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class _CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
    )


class Blob(_CamelModel):
    mime_type: str = Field(default="application/octet-stream")
    data: str


class FileData(_CamelModel):
    mime_type: str | None = None
    file_uri: str


class Part(_CamelModel):
    text: str | None = None
    inline_data: Blob | None = None
    file_data: FileData | None = None


class Content(_CamelModel):
    role: str | None = None
    parts: list[Part] = Field(default_factory=list)


class GenerationConfig(_CamelModel):
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    max_output_tokens: int | None = None
    candidate_count: int | None = None
    stop_sequences: list[str] | None = None
    response_mime_type: str | None = None


class SafetySetting(_CamelModel):
    category: str | None = None
    threshold: str | None = None


class GenerateContentRequest(_CamelModel):
    contents: list[Content]
    system_instruction: Content | None = None
    generation_config: GenerationConfig | None = None
    safety_settings: list[SafetySetting] | None = None
    tools: list[dict] | None = None
    tool_config: dict | None = None
